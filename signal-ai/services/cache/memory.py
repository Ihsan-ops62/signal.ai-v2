import time
import asyncio
from typing import Any, Dict, Optional

class MemoryCache:
    """Simple in-memory TTL cache with async interface."""
    _cache: Dict[str, tuple[Any, float]] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def get(cls, key: str) -> Optional[Any]:
        async with cls._lock:
            entry = cls._cache.get(key)
            if entry:
                value, expires_at = entry
                if expires_at > time.time():
                    return value
                else:
                    del cls._cache[key]
        return None

    @classmethod
    async def set(cls, key: str, value: Any, ttl: int = 300) -> None:
        async with cls._lock:
            cls._cache[key] = (value, time.time() + ttl)

    @classmethod
    async def delete(cls, key: str) -> None:
        async with cls._lock:
            cls._cache.pop(key, None)

    @classmethod
    async def clear(cls) -> None:
        async with cls._lock:
            cls._cache.clear()