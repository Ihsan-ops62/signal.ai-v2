
import logging
import asyncio
from typing import Optional

from openai import AsyncOpenAI, APIError, Timeout

from core.config import settings
from core.exceptions import OpenAIError, TimeoutError
from services.llm.base import BaseLLMService, LLMResponse

logger = logging.getLogger(__name__)


class OpenAIService(BaseLLMService):
    """OpenAI LLM service."""
    
    def __init__(self):
        self.client: AsyncOpenAI | None = None
        self.model = ""
        self.api_key = ""
    
    async def initialize(self) -> None:
        """Initialize OpenAI service."""
        config = settings
        
        if not config.llm.openai_api_key:
            raise OpenAIError("OpenAI API key not configured")
        
        self.api_key = config.llm.openai_api_key
        self.model = config.llm.openai_model
        
        self.client = AsyncOpenAI(api_key=self.api_key)
        
        # Verify connection
        if not await self.health_check():
            raise OpenAIError("Failed to connect to OpenAI API")
        
        logger.info(f"OpenAI service initialized with model: {self.model}")
    
    async def close(self) -> None:
        """Close OpenAI service."""
        if self.client:
            await self.client.close()
            logger.info("OpenAI service closed")
    
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 500,
        temperature: float = 0.7,
        top_p: float = 0.95,
        system_prompt: Optional[str] = None
    ) -> LLMResponse:
        """Generate text using OpenAI."""
        if not self.client:
            raise OpenAIError("Service not initialized")
        
        try:
            messages = []
            
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            
            messages.append({"role": "user", "content": prompt})
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                timeout=60
            )
            
            return LLMResponse(
                text=response.choices[0].message.content,
                tokens_used=response.usage.total_tokens,
                model=self.model,
                provider="openai"
            )
        
        except Timeout:
            raise TimeoutError("OpenAI", "generation", 60)
        except APIError as e:
            logger.error(f"OpenAI API error: {str(e)}")
            raise OpenAIError(f"API error: {str(e)}")
        except Exception as e:
            logger.error(f"OpenAI error: {str(e)}")
            raise OpenAIError(f"Generation failed: {str(e)}")
    
    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 500,
        temperature: float = 0.7
    ) -> LLMResponse:
        """Chat with OpenAI."""
        if not self.client:
            raise OpenAIError("Service not initialized")
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=60
            )
            
            return LLMResponse(
                text=response.choices[0].message.content,
                tokens_used=response.usage.total_tokens,
                model=self.model,
                provider="openai"
            )
        
        except Timeout:
            raise TimeoutError("OpenAI", "chat", 60)
        except APIError as e:
            logger.error(f"OpenAI API error: {str(e)}")
            raise OpenAIError(f"API error: {str(e)}")
        except Exception as e:
            logger.error(f"OpenAI error: {str(e)}")
            raise OpenAIError(f"Chat failed: {str(e)}")
    
    async def health_check(self) -> bool:
        """Check OpenAI health."""
        try:
            # Try a minimal request
            response = await self.client.models.list(timeout=5)
            return response is not None
        except Exception as e:
            logger.warning(f"OpenAI health check failed: {str(e)}")
            return False
