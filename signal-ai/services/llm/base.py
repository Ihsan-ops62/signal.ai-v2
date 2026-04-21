from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Standardized LLM response."""
    text: str
    tokens_used: int = 0
    model: str = ""
    provider: str = ""
    finish_reason: Optional[str] = None


class BaseLLMService(ABC):
    @abstractmethod
    async def generate(self, prompt: str, temperature: float = 0.7) -> str:
        """Generate a complete response."""
        pass

    @abstractmethod
    async def generate_stream(self, prompt: str, temperature: float = 0.7) -> AsyncIterator[str]:
        """Generate a streaming response."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the service is healthy."""
        pass