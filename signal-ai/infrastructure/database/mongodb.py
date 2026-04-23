import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING
from pymongo.errors import OperationFailure
from core.config import config

logger = logging.getLogger(__name__)

class _NullCollection:
    async def insert_one(self, *a, **kw): return None
    async def update_one(self, *a, **kw): return None
    async def find_one(self, *a, **kw): return None
    def find(self, *a, **kw): return self
    async def to_list(self, *a, **kw): return []

class MongoDB:
    client: AsyncIOMotorClient = None
    db = None

    @classmethod
    async def connect(cls):
        try:
            cls.client = AsyncIOMotorClient(config.MONGODB_URI)
            cls.db = cls.client[config.MONGODB_DB_NAME]
            await cls._create_indexes()
            logger.info("MongoDB connected")
        except Exception as e:
            logger.error("MongoDB connection failed: %s", e)
            cls.client = None
            cls.db = None

    @classmethod
    async def _create_indexes(cls):
        """Create indexes, ignoring duplicate/conflict errors."""
        # queries
        try:
            await cls.db.queries.create_index([("created_at", ASCENDING)])
        except OperationFailure:
            pass

        # news
        try:
            await cls.db.news.create_index("url", unique=True)
        except OperationFailure:
            pass

        # posts – drop old conflicting index if it exists
        try:
            await cls.db.posts.drop_index("platform_post_id_sparse")
        except OperationFailure:
            pass
        try:
            await cls.db.posts.create_index(
                [("platform_post_id", ASCENDING), ("platform", ASCENDING)],
                unique=True,
                sparse=True,
                name="platform_post_id_platform_unique"
            )
        except OperationFailure:
            pass

        # sessions
        try:
            await cls.db.sessions.create_index("session_id", unique=True)
        except OperationFailure:
            pass

        # contexts
        try:
            await cls.db.contexts.create_index("session_id", unique=True)
        except OperationFailure:
            pass

        # user_tokens
        try:
            await cls.db.user_tokens.create_index(
                [("username", ASCENDING), ("platform", ASCENDING)], unique=True
            )
        except OperationFailure:
            pass

        # token_blacklist (TTL index)
        try:
            await cls.db.token_blacklist.create_index("expires_at", expireAfterSeconds=0)
        except OperationFailure:
            pass

    @classmethod
    async def close(cls):
        if cls.client:
            cls.client.close()

    @classmethod
    def get_collection(cls, name: str):
        if cls.db is None:
            return _NullCollection()
        return cls.db[name]

    @classmethod
    def get_db(cls):
        return cls.db

def get_mongodb():
    return MongoDB.get_db()