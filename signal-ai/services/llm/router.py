
import logging
from typing import AsyncIterator, Optional
from services.llm.base import BaseLLMService
from services.llm.ollama import OllamaService

logger = logging.getLogger(__name__)


class LLMRouter(BaseLLMService):
    """Routes LLM requests to primary service, with optional fallback."""

    def __init__(self, fallback_service: Optional[BaseLLMService] = None):
        self.primary = OllamaService()
        self.fallback = fallback_service

    async def generate(self, prompt: str, temperature: float = 0.7) -> str:
        try:
            return await self.primary.generate(prompt, temperature)
        except Exception as e:
            if self.fallback:
                logger.warning("Primary LLM failed (%s), using fallback", e)
                return await self.fallback.generate(prompt, temperature)
            raise

    async def generate_stream(self, prompt: str, temperature: float = 0.7) -> AsyncIterator[str]:
        try:
            async for chunk in self.primary.generate_stream(prompt, temperature):
                yield chunk
        except Exception as e:
            if self.fallback:
                logger.warning("Primary LLM stream failed (%s), using fallback", e)
                async for chunk in self.fallback.generate_stream(prompt, temperature):
                    yield chunk
            else:
                raise

    async def health_check(self) -> bool:
        return await self.primary.health_check()


# Singleton getter
_llm_router: Optional[LLMRouter] = None


async def get_llm_router() -> LLMRouter:
    """Get or create LLM router singleton."""
    global _llm_router
    if _llm_router is None:
        _llm_router = LLMRouter()
    return _llm_router