"""
Database migrations for Signal AI.
Run migrations before deploying updates.
"""

import asyncio
import logging
from datetime import datetime

from infrastructure.database.mongodb import MongoDB
from core.config import settings

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def migrate_mongodb():
    """Run MongoDB migrations (create indexes)."""
    logger.info("Starting MongoDB migrations...")
    
    try:
        # Connect to MongoDB (indexes are created on connect)
        await MongoDB.connect()
        
        # Verify connection
        collection = MongoDB.get_collection("migrations")
        await collection.find_one({})
        
        logger.info("MongoDB collections and indexes ready")
        
        # Check if migration already recorded
        existing = await collection.find_one({"name": "initial_schema"})
        if existing:
            logger.info("Migration 'initial_schema' already applied")
            return True
        
        # Record migration
        migration = {
            "name": "initial_schema",
            "applied_at": datetime.utcnow(),
            "status": "completed"
        }
        await collection.insert_one(migration)
        
        logger.info("MongoDB migrations completed successfully")
        return True
    
    except Exception as e:
        logger.error(f"MongoDB migration failed: {str(e)}")
        return False


async def migrate_add_fields():
    """Add new fields to existing documents (idempotent)."""
    logger.info("Adding default fields to users collection...")
    
    try:
        users_coll = MongoDB.get_collection("users")
        
        # Update users missing preferences
        result = await users_coll.update_many(
            {"preferences": {"$exists": False}},
            {"$set": {"preferences": {}}}
        )
        logger.info(f"Updated {result.modified_count} users with default preferences")
        
        # Add last_login if missing
        result = await users_coll.update_many(
            {"last_login": {"$exists": False}},
            {"$set": {"last_login": None}}
        )
        logger.info(f"Updated {result.modified_count} users with last_login field")
        
        return True
    
    except Exception as e:
        logger.error(f"Field migration failed: {str(e)}")
        return False


async def run_migrations():
    """Run all pending migrations."""
    logger.info("=" * 50)
    logger.info("Signal AI Database Migrations")
    logger.info("=" * 50)
    
    try:
        # MongoDB migrations (primary)
        mongo_success = await migrate_mongodb()
        
        # Additional field migrations
        fields_success = await migrate_add_fields()
        
        # PostgreSQL is not configured yet; skip
        logger.info("PostgreSQL migrations skipped (not configured)")
        
        if mongo_success and fields_success:
            logger.info("✅ All migrations completed successfully")
            return 0
        else:
            logger.error("❌ Some migrations failed")
            return 1
    
    except Exception as e:
        logger.error(f"Migration error: {str(e)}")
        return 1
    finally:
        await MongoDB.close()


if __name__ == "__main__":
    exit_code = asyncio.run(run_migrations())
    exit(exit_code)