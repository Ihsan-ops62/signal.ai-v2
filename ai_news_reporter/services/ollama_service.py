import asyncio
import logging
from langchain_ollama import ChatOllama
from config import config

logger = logging.getLogger(__name__)


class OllamaService:
    """Wrapper around a local Ollama LLM.

    A single ChatOllama instance is created at startup and reused for all
    requests.  A fresh instance is created only when ``temperature`` differs
    from the default, keeping the common path fast while still allowing
    per-call temperature overrides.

    Performance tips:
    - Use a smaller/faster model: set OLLAMA_MODEL=llama3.2:3b or phi3:mini
    - Ensure Ollama has GPU access: `ollama run <model> --num-gpu 1`
    - Increase context size if needed (not set here, uses Ollama default)
    """

    _DEFAULT_TEMPERATURE: float = 0.7
    _LLM_TIMEOUT: float = 400.0  # 400 seconds – generous for slow hardware

    def __init__(self) -> None:
        self.base_url: str = config.OLLAMA_BASE_URL
        self.model: str = config.OLLAMA_MODEL
        # Reusable default instance – avoids object-creation overhead on every call
        self._default_llm = ChatOllama(
            base_url=self.base_url,
            model=self.model,
            temperature=self._DEFAULT_TEMPERATURE,
        )

    async def generate(self, prompt: str, temperature: float = _DEFAULT_TEMPERATURE) -> str:
        """Invoke the LLM and return the response text.

        Args:
            prompt: The full prompt string to send.
            temperature: Sampling temperature.  When it matches the default a
                cached instance is used; otherwise a fresh one is created.

        Returns:
            The model's response as a plain string.

        Raises:
            RuntimeError: Wraps any underlying LLM error so callers get a
                consistent exception type.
        """
        try:
            # Reuse the default instance when possible
            if temperature == self._DEFAULT_TEMPERATURE:
                llm = self._default_llm
            else:
                llm = ChatOllama(
                    base_url=self.base_url,
                    model=self.model,
                    temperature=temperature,
                )

            # Add timeout to prevent hanging indefinitely
            response = await asyncio.wait_for(
                llm.ainvoke(prompt),
                timeout=self._LLM_TIMEOUT
            )
            return response.content

        except asyncio.TimeoutError:
            logger.error("LLM call timed out after %.1f seconds", self._LLM_TIMEOUT)
            raise RuntimeError(f"LLM call timed out after {self._LLM_TIMEOUT} seconds") from None
        except Exception as exc:
            logger.error("Ollama generation failed: %s", exc)
            raise RuntimeError(f"LLM generation failed: {exc}") from exc