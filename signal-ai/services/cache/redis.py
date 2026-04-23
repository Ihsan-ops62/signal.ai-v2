import os
import json
import logging
from typing import Optional, Any
import redis.asyncio as redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

class RedisCache:
    _client: Optional[redis.Redis] = None

    @classmethod
    async def get_client(cls) -> redis.Redis:
        if cls._client is None:
            cls._client = redis.from_url(REDIS_URL, decode_responses=True)
            await cls._client.ping()
            logger.info("Redis connected at %s", REDIS_URL)
        return cls._client

    @classmethod
    async def get(cls, key: str) -> Optional[Any]:
        client = await cls.get_client()
        value = await client.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return None

    @classmethod
    async def set(cls, key: str, value: Any, ttl: int = 300) -> None:
        client = await cls.get_client()
        if not isinstance(value, str):
            value = json.dumps(value)
        await client.set(key, value, ex=ttl)

    @classmethod
    async def delete(cls, key: str) -> None:
        client = await cls.get_client()
        await client.delete(key)

    @classmethod
    async def close(cls):
        if cls._client:
            await cls._client.close()
            cls._client = None