
import logging
from typing import Optional
from fastapi import Request, HTTPException, Depends
from core.config import settings
from api.dependencies.auth import get_optional_user
from services.cache.redis import get_cache

logger = logging.getLogger(__name__)


class RateLimitKey:
    @staticmethod
    def for_user(user_id: str) -> str:
        return f"rate_limit:user:{user_id}"
    
    @staticmethod
    def for_ip(ip: str) -> str:
        return f"rate_limit:ip:{ip}"


async def check_rate_limit(
    request: Request,
    current_user = Depends(get_optional_user)
) -> None:
    """Check rate limiting."""
    try:
        cache = await get_cache()
        
        if current_user:
            key = RateLimitKey.for_user(current_user.sub)
            limit = 100  # Higher limit for authenticated users
        else:
            client_ip = request.client.host if request.client else "unknown"
            key = RateLimitKey.for_ip(client_ip)
            limit = 30  # Lower limit for anonymous
        
        current = await cache.increment(key, 1)
        
        if current == 1:
            # Set expiry on first request (60 seconds window)
            await cache.set(key, current, ttl=60)
        
        if current > limit:
            logger.warning(f"Rate limit exceeded for {key}")
            raise HTTPException(status_code=429, detail="Too many requests")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rate limit check failed: {e}")
        # Fail open - allow request
        pass