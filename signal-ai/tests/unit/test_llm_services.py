"""
Unit tests for LLM services.
"""

import pytest
from unittest.mock import AsyncMock, patch

from services.llm.ollama import OllamaService
from services.llm.openai import OpenAIService
from services.llm.router import LLMRouter
from core.exceptions import LLMError, OllamaError


@pytest.mark.asyncio
class TestOllamaService:
    """Tests for OllamaService."""
    
    @pytest.fixture
    async def service(self):
        """Create service instance."""
        service = OllamaService()
        yield service
    
    @pytest.mark.asyncio
    async def test_initialize(self, service):
        """Test service initialization."""
        with patch("aiohttp.ClientSession"):
            await service.initialize()
            assert service.session is not None
    
    @pytest.mark.asyncio
    async def test_generate_success(self, service):
        """Test successful generation."""
        with patch.object(service, "session") as mock_session:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={
                "response": "Test response",
                "eval_count": 10
            })
            mock_session.post = AsyncMock(return_value=mock_response)
            
            await service.initialize()
            result = await service.generate("Test prompt")
            
            assert result.text == "Test response"
            assert result.tokens_used == 10
    
    @pytest.mark.asyncio
    async def test_generate_failure(self, service):
        """Test generation failure."""
        with patch.object(service, "session") as mock_session:
            mock_session.post = AsyncMock(side_effect=Exception("Connection error"))
            
            await service.initialize()
            
            with pytest.raises(OllamaError):
                await service.generate("Test prompt")
    
    @pytest.mark.asyncio
    async def test_health_check(self, service):
        """Test health check."""
        with patch.object(service, "session") as mock_session:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={"models": []})
            mock_session.get = AsyncMock(return_value=mock_response)
            
            await service.initialize()
            result = await service.health_check()
            
            assert result is True


@pytest.mark.asyncio
class TestOpenAIService:
    """Tests for OpenAIService."""
    
    @pytest.fixture
    async def service(self):
        """Create service instance."""
        service = OpenAIService()
        yield service
    
    @pytest.mark.asyncio
    async def test_initialize(self, service):
        """Test service initialization."""
        with patch("openai.AsyncOpenAI"):
            await service.initialize()
            assert service.client is not None
    
    @pytest.mark.asyncio
    async def test_generate_success(self, service):
        """Test successful generation."""
        with patch("openai.AsyncOpenAI"):
            service.client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.choices = [AsyncMock(message=AsyncMock(content="Test response"))]
            mock_response.usage = AsyncMock(total_tokens=10)
            
            service.client.chat.completions.create = AsyncMock(return_value=mock_response)
            
            result = await service.generate("Test prompt")
            
            assert result.text == "Test response"
            assert result.tokens_used == 10


@pytest.mark.asyncio
class TestLLMRouter:
    """Tests for LLMRouter."""
    
    @pytest.mark.asyncio
    async def test_failover(self):
        """Test failover from primary to fallback."""
        primary = AsyncMock()
        fallback = AsyncMock()
        
        # Primary fails, fallback succeeds
        primary.generate = AsyncMock(side_effect=Exception("Primary down"))
        fallback.generate = AsyncMock(return_value=AsyncMock(text="Fallback response"))
        
        router = LLMRouter(primary, fallback)
        result = await router.generate("Test prompt")
        
        assert result.text == "Fallback response"
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health check with primary down."""
        primary = AsyncMock()
        fallback = AsyncMock()
        
        primary.health_check = AsyncMock(return_value=False)
        fallback.health_check = AsyncMock(return_value=True)
        
        router = LLMRouter(primary, fallback)
        result = await router.health_check()
        
        assert result is True
