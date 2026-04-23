import json
import logging
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime

import redis.asyncio as redis
from core.config import config

logger = logging.getLogger(__name__)

class SessionManager:
    """Manages conversation sessions with Redis backend."""
    
    _redis: Optional[redis.Redis] = None
    _lock = asyncio.Lock()
    
    # Key prefixes for Redis
    _CONTEXT_PREFIX = "session:context:"
    _PENDING_SESSION_PREFIX = "session:pending:"
    _GRAPH_STATE_PREFIX = "session:graph_state:"
    
    # TTL for session data (7 days)
    _SESSION_TTL = 7 * 24 * 60 * 60
    
    @classmethod
    async def connect(cls) -> None:
        """Initialize Redis connection (call once at startup)."""
        if cls._redis is not None:
            return
        
        try:
            async with cls._lock:
                if cls._redis is not None:
                    return
                
                
                kwargs = {
                    "host": config.REDIS_HOST,
                    "port": config.REDIS_PORT,
                    "db": config.REDIS_DB,
                    "decode_responses": True,
                    "socket_timeout": 10.0,
                    "socket_connect_timeout": 10.0,
                }

                cls._redis = redis.Redis(**kwargs)
                await cls._redis.ping()
                logger.info("✓ Redis session manager connected")
        except Exception as e:
            logger.error("✗ Redis connection failed: %s", e)
            cls._redis = None
            raise
    
    @classmethod
    async def close(cls) -> None:
        if cls._redis:
            await cls._redis.close()
            cls._redis = None
            logger.info("Redis session manager disconnected")
    
    @classmethod
    async def _get_redis(cls) -> redis.Redis:
        if cls._redis is None:
            await cls.connect()
        return cls._redis
    
    @classmethod
    async def save_context(
        cls, session_id: str, context: List[Dict[str, str]], user_id: Optional[str] = None
    ) -> None:
        try:
            redis_client = await cls._get_redis()
            key = f"{cls._CONTEXT_PREFIX}{session_id}"
            data = {
                "context": context,
                "user_id": user_id,
                "updated_at": datetime.utcnow().isoformat(),
            }
            await redis_client.setex(key, cls._SESSION_TTL, json.dumps(data))
            logger.debug(f"Saved context for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to save context for {session_id}: {e}")
            raise
    
    @classmethod
    async def load_context(cls, session_id: str) -> Optional[List[Dict[str, str]]]:
        try:
            redis_client = await cls._get_redis()
            key = f"{cls._CONTEXT_PREFIX}{session_id}"
            data_str = await redis_client.get(key)
            if not data_str:
                return None
            data = json.loads(data_str)
            return data.get("context", [])
        except Exception as e:
            logger.error(f"Failed to load context for {session_id}: {e}")
            return None
    
    @classmethod
    async def save_pending_session(
        cls, session_id: str, pending_data: Dict[str, Any], user_id: Optional[str] = None
    ) -> None:
        try:
            redis_client = await cls._get_redis()
            key = f"{cls._PENDING_SESSION_PREFIX}{session_id}"
            data = {
                "pending": pending_data,
                "user_id": user_id,
                "saved_at": datetime.utcnow().isoformat(),
            }
            await redis_client.setex(key, cls._SESSION_TTL, json.dumps(data))
        except Exception as e:
            logger.error(f"Failed to save pending session {session_id}: {e}")
            raise
    
    @classmethod
    async def load_pending_session(cls, session_id: str) -> Optional[Dict[str, Any]]:
        try:
            redis_client = await cls._get_redis()
            key = f"{cls._PENDING_SESSION_PREFIX}{session_id}"
            data_str = await redis_client.get(key)
            if not data_str:
                return None
            data = json.loads(data_str)
            return data.get("pending")
        except Exception as e:
            logger.error(f"Failed to load pending session: {e}")
            return None
    
    @classmethod
    async def save_graph_state(
        cls, session_id: str, graph_state: Dict[str, Any], user_id: Optional[str] = None
    ) -> None:
        try:
            redis_client = await cls._get_redis()
            key = f"{cls._GRAPH_STATE_PREFIX}{session_id}"
            data = {
                "state": graph_state,
                "user_id": user_id,
                "saved_at": datetime.utcnow().isoformat(),
            }
            await redis_client.setex(key, cls._SESSION_TTL, json.dumps(data))
        except Exception as e:
            logger.error(f"Failed to save graph state: {e}")
            raise
    
    @classmethod
    async def load_graph_state(cls, session_id: str) -> Optional[Dict[str, Any]]:
        try:
            redis_client = await cls._get_redis()
            key = f"{cls._GRAPH_STATE_PREFIX}{session_id}"
            data_str = await redis_client.get(key)
            if not data_str:
                return None
            data = json.loads(data_str)
            return data.get("state")
        except Exception as e:
            logger.error(f"Failed to load graph state: {e}")
            return None
    
    @classmethod
    async def delete_session(cls, session_id: str) -> None:
        try:
            redis_client = await cls._get_redis()
            keys = [
                f"{cls._CONTEXT_PREFIX}{session_id}",
                f"{cls._PENDING_SESSION_PREFIX}{session_id}",
                f"{cls._GRAPH_STATE_PREFIX}{session_id}",
            ]
            for key in keys:
                await redis_client.delete(key)
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
    
    @classmethod
    async def clear_expired_sessions(cls, hours: int = 8 * 24) -> int:
        try:
            redis_client = await cls._get_redis()
            pattern = f"{cls._CONTEXT_PREFIX}*"
            keys = await redis_client.keys(pattern)
            return len(keys)
        except Exception as e:
            return 0