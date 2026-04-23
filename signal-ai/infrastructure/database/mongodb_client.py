
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncClient, AsyncDatabase, AsyncCollection
from pymongo import ASCENDING, DESCENDING, HASHED
from pymongo.errors import PyMongoError

from core.config import settings
from core.exceptions import DatabaseError

logger = logging.getLogger(__name__)


class MongoDB:
    """Singleton MongoDB client for async operations"""
    
    _instance: Optional['MongoDB'] = None
    _client: Optional[AsyncClient] = None
    _db: Optional[AsyncDatabase] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    async def connect(cls) -> None:
        """Initialize MongoDB connection"""
        if cls._client is not None:
            logger.info("MongoDB already connected")
            return
        
        try:
            cls._client = AsyncClient(
                settings.MONGODB_URL,
                serverSelectionTimeoutMS=5000,
                socketTimeoutMS=None,
                connectTimeoutMS=10000,
                maxPoolSize=50,
                minPoolSize=10,
            )
            # Test connection
            await cls._client.admin.command('ping')
            cls._db = cls._client[settings.MONGODB_DB]
            await cls._create_indexes()
            logger.info(f"✓ MongoDB connected: {settings.MONGODB_DB}")
        except PyMongoError as e:
            logger.error(f"✗ MongoDB connection failed: {e}")
            raise DatabaseError(f"MongoDB connection failed: {e}")
    
    @classmethod
    async def disconnect(cls) -> None:
        """Close MongoDB connection"""
        if cls._client:
            cls._client.close()
            cls._client = None
            cls._db = None
            logger.info("MongoDB disconnected")
    
    @classmethod
    def get_db(cls) -> AsyncDatabase:
        """Get database instance"""
        if cls._db is None:
            raise DatabaseError("MongoDB not connected. Call connect() first")
        return cls._db
    
    @classmethod
    def get_collection(cls, name: str) -> AsyncCollection:
        """Get collection by name"""
        return cls.get_db()[name]
    
    @classmethod
    async def _create_indexes(cls) -> None:
        """Create all required indexes"""
        if cls._db is None:
            return
        
        try:
            # Users
            await cls._db["users"].create_index("username", unique=True)
            await cls._db["users"].create_index("email", unique=True, sparse=True)
            
            # OAuth Tokens
            await cls._db["oauth_tokens"].create_index([("user_id", ASCENDING), ("platform", ASCENDING)])
            await cls._db["oauth_tokens"].create_index("expires_at", expireAfterSeconds=0)  # TTL
            
            # Connections
            await cls._db["connections"].create_index([("user_id", ASCENDING), ("platform", ASCENDING)])
            
            # News Articles
            await cls._db["news"].create_index("url", unique=True)
            await cls._db["news"].create_index("published_at", sparse=True)
            
            # Social Posts
            await cls._db["posts"].create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
            await cls._db["posts"].create_index([("platform_post_id", ASCENDING), ("platform", ASCENDING)], sparse=True)
            await cls._db["posts"].create_index("content_hash", sparse=True)
            
            # Rate Limits
            await cls._db["rate_limits"].create_index([("user_id", ASCENDING), ("platform", ASCENDING)])
            await cls._db["rate_limits"].create_index("window_end", expireAfterSeconds=0)  # TTL
            
            # Conversations
            await cls._db["contexts"].create_index([("session_id", ASCENDING)])
            await cls._db["contexts"].create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)])
            
            # Session State
            await cls._db["sessions"].create_index("session_id", unique=True)
            await cls._db["sessions"].create_index("expires_at", expireAfterSeconds=0)  # TTL
            
            # Activity
            await cls._db["activity"].create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
            
            logger.debug("✓ MongoDB indexes created")
        except Exception as e:
            logger.warning(f"⚠️  Failed to create indexes: {e}")
    
    @classmethod
    async def insert_one(cls, collection_name: str, document: Dict) -> str:
        """Insert single document, return inserted_id"""
        try:
            result = await cls.get_collection(collection_name).insert_one(document)
            return str(result.inserted_id)
        except PyMongoError as e:
            raise DatabaseError(f"Insert failed: {e}")
    
    @classmethod
    async def find_one(cls, collection_name: str, query: Dict) -> Optional[Dict]:
        """Find single document"""
        try:
            return await cls.get_collection(collection_name).find_one(query)
        except PyMongoError as e:
            raise DatabaseError(f"Find failed: {e}")
    
    @classmethod
    async def find_many(cls, collection_name: str, query: Dict = None, skip: int = 0, limit: int = 100) -> List[Dict]:
        """Find multiple documents with pagination"""
        try:
            cursor = cls.get_collection(collection_name).find(query or {}).skip(skip).limit(limit)
            return await cursor.to_list(limit)
        except PyMongoError as e:
            raise DatabaseError(f"Find failed: {e}")
    
    @classmethod
    async def update_one(cls, collection_name: str, query: Dict, update: Dict, upsert: bool = False) -> int:
        """Update single document, return modified_count"""
        try:
            result = await cls.get_collection(collection_name).update_one(
                query, {"$set": update}, upsert=upsert
            )
            return result.modified_count
        except PyMongoError as e:
            raise DatabaseError(f"Update failed: {e}")
    
    @classmethod
    async def delete_one(cls, collection_name: str, query: Dict) -> int:
        """Delete single document, return deleted_count"""
        try:
            result = await cls.get_collection(collection_name).delete_one(query)
            return result.deleted_count
        except PyMongoError as e:
            raise DatabaseError(f"Delete failed: {e}")
    
    @classmethod
    async def delete_many(cls, collection_name: str, query: Dict) -> int:
        """Delete multiple documents"""
        try:
            result = await cls.get_collection(collection_name).delete_many(query)
            return result.deleted_count
        except PyMongoError as e:
            raise DatabaseError(f"Delete failed: {e}")
    
    @classmethod
    async def count(cls, collection_name: str, query: Dict = None) -> int:
        """Count documents matching query"""
        try:
            return await cls.get_collection(collection_name).count_documents(query or {})
        except PyMongoError as e:
            raise DatabaseError(f"Count failed: {e}")
