"""
Redis cache service for Signal AI.
High-performance caching with automatic expiration.
"""

import logging
import json
import time
from typing import Any, Optional

from redis.asyncio import Redis

from core.config import settings
from core.exceptions import CacheError

logger = logging.getLogger(__name__)


class RedisCache:
    """Redis cache implementation."""
    
    def __init__(self):
        self.redis: Redis | None = None
        self.ttl = 3600  # Default 1 hour
    
    async def connect(self) -> None:
        """Initialize Redis connection."""
        # Use default TTL (can be overridden by env if added later)
        self.ttl = getattr(settings, 'REDIS_TTL', 3600)
        redis_url = settings.REDIS_DSN
        
        try:
            self.redis = await Redis.from_url(
                redis_url,
                encoding="utf8",
                decode_responses=True
            )
            await self.redis.ping()
            logger.info("Redis cache connected")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")
            raise CacheError(f"Redis connection failed: {str(e)}")
    
    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
            logger.info("Redis cache closed")
    
    async def get(self, key: str) -> Any | None:
        """Get value from cache."""
        try:
            value = await self.redis.get(key)
            if value:
                return json.loads(value)
            return None
        except json.JSONDecodeError:
            return value
        except Exception as e:
            logger.error(f"Cache get failed: {str(e)}")
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None
    ) -> bool:
        """Set value in cache."""
        try:
            ttl = ttl or self.ttl
            json_value = json.dumps(value) if not isinstance(value, str) else value
            await self.redis.setex(key, ttl, json_value)
            return True
        except Exception as e:
            logger.error(f"Cache set failed: {str(e)}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache."""
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete failed: {str(e)}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        try:
            return await self.redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Cache exists check failed: {str(e)}")
            return False
    
    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment counter."""
        try:
            return await self.redis.incrby(key, amount)
        except Exception as e:
            logger.error(f"Cache increment failed: {str(e)}")
            return 0
    
    async def flush(self) -> bool:
        """Flush all cache."""
        try:
            await self.redis.flushdb()
            return True
        except Exception as e:
            logger.error(f"Cache flush failed: {str(e)}")
            return False
    
    async def health_check(self) -> bool:
        """Check Redis health."""
        try:
            return await self.redis.ping()
        except:
            return False


class MemoryCache:
    """In-memory cache implementation (fallback)."""
    
    def __init__(self):
        self.cache: dict[str, tuple[Any, float]] = {}
        self.ttl = 3600
    
    async def connect(self) -> None:
        """Initialize memory cache."""
        logger.info("Memory cache initialized")
    
    async def close(self) -> None:
        """Close memory cache."""
        self.cache.clear()
        logger.info("Memory cache closed")
    
    async def get(self, key: str) -> Any | None:
        """Get value from cache."""
        if key in self.cache:
            value, expiry = self.cache[key]
            if expiry > time.time():
                return value
            else:
                del self.cache[key]
        return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None
    ) -> bool:
        """Set value in cache."""
        ttl = ttl or self.ttl
        self.cache[key] = (value, time.time() + ttl)
        return True
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache."""
        if key in self.cache:
            del self.cache[key]
        return True
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        return key in self.cache
    
    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment counter."""
        value = 0
        if key in self.cache:
            value = self.cache[key][0]
        value += amount
        self.cache[key] = (value, float('inf'))
        return value
    
    async def flush(self) -> bool:
        """Flush all cache."""
        self.cache.clear()
        return True
    
    async def health_check(self) -> bool:
        """Check cache health."""
        return True


# Global instances
_cache_instance = None


async def get_cache():
    """Get cache instance (Redis with fallback to memory)."""
    global _cache_instance
    if _cache_instance is None:
        try:
            _cache_instance = RedisCache()
            await _cache_instance.connect()
        except Exception as e:
            logger.warning(f"Redis cache unavailable, using memory cache: {str(e)}")
            _cache_instance = MemoryCache()
            await _cache_instance.connect()
    return _cache_instance