import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING
from pymongo.errors import OperationFailure
from core.config import settings

logger = logging.getLogger(__name__)


class _NullCollection:
    async def insert_one(self, *a, **kw):
        return None

    async def update_one(self, *a, **kw):
        return None

    async def find_one(self, *a, **kw):
        return None

    async def create_index(self, *a, **kw):
        return None

    def find(self, *a, **kw):
        return self

    async def to_list(self, *a, **kw):
        return []


class MongoDB:
    client: AsyncIOMotorClient = None
    db = None

    @classmethod
    async def connect(cls):
        try:
            cls.client = AsyncIOMotorClient(settings.MONGODB_URI)
            cls.db = cls.client[settings.MONGODB_DB_NAME]

            # queries collection index
            try:
                await cls.db.queries.create_index([("created_at", ASCENDING)])
            except OperationFailure as e:
                if "already exists" not in str(e).lower():
                    raise

            # news collection unique URL index
            try:
                await cls.db.news.create_index("url", unique=True)
            except OperationFailure as e:
                if "already exists" not in str(e).lower():
                    raise

            # posts index – platform_post_id sparse unique
            try:
                await cls.db.posts.create_index(
                    "platform_post_id",
                    unique=True,
                    sparse=True,
                    name="platform_post_id_sparse",
                )
            except OperationFailure as e:
                err = str(e).lower()
                if "already exists" in err:
                    logger.debug("posts index already exists")
                elif "index key" in err or "different options" in err:
                    logger.warning("Recreating stale posts index")
                    try:
                        await cls.db.posts.drop_index("linkedin_post_id_sparse")
                    except Exception:
                        pass
                    try:
                        await cls.db.posts.drop_index("linkedin_post_id_1")
                    except Exception:
                        pass
                    await cls.db.posts.create_index(
                        "platform_post_id",
                        unique=True,
                        sparse=True,
                        name="platform_post_id_sparse",
                    )
                else:
                    raise

            # sessions collection
            try:
                await cls.db.sessions.create_index("session_id", unique=True)
            except OperationFailure:
                pass
            try:
                await cls.db.sessions.create_index("updated_at")
            except OperationFailure:
                pass

            # contexts collection
            try:
                await cls.db.contexts.create_index("session_id", unique=True)
            except OperationFailure:
                pass
            try:
                await cls.db.contexts.create_index("user_id")
            except OperationFailure:
                pass
            try:
                await cls.db.contexts.create_index([("user_id", 1), ("session_id", 1)])
            except OperationFailure:
                pass

            # user_tokens collection
            try:
                await cls.db.user_tokens.create_index(
                    [("username", ASCENDING), ("platform", ASCENDING)],
                    unique=True
                )
            except OperationFailure:
                pass

            # token_blacklist TTL index
            try:
                await cls.db.token_blacklist.create_index("expires_at", expireAfterSeconds=0)
            except OperationFailure:
                pass

            # user_rate_limits index
            try:
                await cls.db.user_rate_limits.create_index(
                    [("username", 1), ("platform", 1)],
                    unique=True
                )
            except OperationFailure:
                pass

            logger.info("MongoDB connected and indexes ready")

        except Exception as exc:
            logger.error("MongoDB connection failed: %s — running without database", exc)
            cls.client = None
            cls.db = None

    @classmethod
    async def close(cls):
        if cls.client:
            cls.client.close()

    @classmethod
    def get_collection(cls, name: str):
        if cls.db is None:
            logger.debug("MongoDB unavailable — returning NullCollection for '%s'", name)
            return _NullCollection()
        return cls.db[name]


async def get_mongodb():
    """Get MongoDB instance, ensuring connection."""
    await MongoDB.connect()
    return MongoDB