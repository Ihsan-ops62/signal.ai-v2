import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING
from pymongo.errors import OperationFailure
from config import config

logger = logging.getLogger(__name__)

class MongoDB:
    client: AsyncIOMotorClient = None
    db = None

    @classmethod
    async def connect(cls):
        try:
            cls.client = AsyncIOMotorClient(config.MONGODB_URI)
            cls.db = cls.client[config.MONGODB_DB_NAME]

            # Create indexes safely
            # queries index
            try:
                await cls.db.queries.create_index([("created_at", ASCENDING)])
            except OperationFailure as e:
                if "already exists" in str(e).lower():
                    logger.debug("Index on 'queries.created_at' already exists")
                else:
                    raise

            # news index
            try:
                await cls.db.news.create_index("url", unique=True)
            except OperationFailure as e:
                if "already exists" in str(e).lower():
                    logger.debug("Index on 'news.url' already exists")
                else:
                    raise

            # posts index - handle conflict by dropping existing index if needed
            try:
                await cls.db.posts.create_index(
                    "linkedin_post_id",
                    unique=True,
                    sparse=True,
                    name="linkedin_post_id_sparse"  # use unique name to avoid conflict
                )
            except OperationFailure as e:
                if "already exists" in str(e).lower() and "sparse" in str(e):
                    # Try to drop the old index and recreate
                    logger.warning("Dropping existing posts index to recreate with sparse=True")
                    try:
                        await cls.db.posts.drop_index("linkedin_post_id_1")
                        # Now create with correct options
                        await cls.db.posts.create_index(
                            "linkedin_post_id",
                            unique=True,
                            sparse=True,
                            name="linkedin_post_id_sparse"
                        )
                    except Exception as drop_err:
                        logger.warning(f"Could not drop index: {drop_err}")
                else:
                    raise

            logger.info("MongoDB connected and indexes ready")

        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}. Continuing without database.")
            cls.client = None
            cls.db = None

    @classmethod
    async def close(cls):
        if cls.client:
            cls.client.close()

    @classmethod
    def get_collection(cls, name: str):
        if cls.db is None:
            raise RuntimeError("MongoDB not connected")
        return cls.db[name]