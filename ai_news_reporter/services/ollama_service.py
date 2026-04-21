import asyncio
import logging
from typing import AsyncIterator

import httpx
from langchain_ollama import ChatOllama
from config import config

logger = logging.getLogger(__name__)


class OllamaService:

    _DEFAULT_TEMPERATURE: float = 0.7
    _LLM_TIMEOUT: float = 12000.0   # 120 seconds (was 400000)
    def __init__(self) -> None:
        self.base_url: str = config.OLLAMA_BASE_URL
        self.model: str = config.OLLAMA_MODEL
        self._default_llm = ChatOllama(
            base_url=self.base_url,
            model=self.model,
            temperature=self._DEFAULT_TEMPERATURE,
        )

    def _get_llm(self, temperature: float) -> ChatOllama:
        if temperature == self._DEFAULT_TEMPERATURE:
            return self._default_llm
        return ChatOllama(
            base_url=self.base_url,
            model=self.model,
            temperature=temperature,
        )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code != 200:
                    logger.warning("Ollama health check: HTTP %d", resp.status_code)
                    return False
                data = resp.json()
                models = [m["name"] for m in data.get("models", [])]
                if not any(self.model in m for m in models):
                    logger.warning("Model %s not found in Ollama", self.model)
                    return False
                logger.info("Ollama health check passed (model: %s)", self.model)
                return True
        except httpx.ConnectError:
            logger.error("Ollama not reachable at %s", self.base_url)
            return False
        except Exception as e:
            logger.error("Ollama health check failed: %s", e)
            return False

    async def generate(self, prompt: str, temperature: float = _DEFAULT_TEMPERATURE) -> str:
        try:
            llm = self._get_llm(temperature)
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

    async def generate_stream(
        self, prompt: str, temperature: float = _DEFAULT_TEMPERATURE
    ) -> AsyncIterator[str]:
        llm = self._get_llm(temperature)
        try:
            async for chunk in llm.astream(prompt):
                if chunk.content:
                    yield chunk.content
        except asyncio.TimeoutError:
            logger.error("LLM streaming timed out after %.1f seconds", self._LLM_TIMEOUT)
            yield " [Error: LLM timeout]"
        except Exception as exc:
            logger.error("Ollama streaming failed: %s", exc)
            yield f" [Error: {exc}]"