"""
Seed database with sample data for development and testing.
"""

import asyncio
import logging
from datetime import datetime, timedelta
import random

from infrastructure.database.mongodb import get_mongodb
from core.security import hash_password

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def seed_users():
    """Create sample users."""
    logger.info("Seeding users...")
    
    mongodb = await get_mongodb()
    
    users = [
        {
            "email": "alice@example.com",
            "password_hash": hash_password("password123"),
            "name": "Alice Johnson",
            "created_at": datetime.utcnow(),
            "preferences": {
                "interests": ["technology", "business", "science"],
                "notification_frequency": "daily"
            }
        },
        {
            "email": "bob@example.com",
            "password_hash": hash_password("password123"),
            "name": "Bob Smith",
            "created_at": datetime.utcnow(),
            "preferences": {
                "interests": ["sports", "entertainment"],
                "notification_frequency": "weekly"
            }
        },
        {
            "email": "charlie@example.com",
            "password_hash": hash_password("password123"),
            "name": "Charlie Davis",
            "created_at": datetime.utcnow(),
            "preferences": {
                "interests": ["AI", "crypto", "tech"],
                "notification_frequency": "realtime"
            }
        }
    ]
    
    for user in users:
        await mongodb.insert_one("users", user)
    
    logger.info(f"✅ Created {len(users)} sample users")


async def seed_articles():
    """Create sample news articles."""
    logger.info("Seeding articles...")
    
    mongodb = await get_mongodb()
    
    articles = [
        {
            "title": "AI Breakthroughs Accelerate in 2025",
            "description": "New AI models show unprecedented capabilities",
            "content": "Recent advances in large language models have demonstrated remarkable progress. Researchers have successfully created more efficient models that require less computational resources while maintaining superior performance.",
            "url": "https://example.com/ai-2025",
            "source": "TechNews",
            "published_at": datetime.utcnow() - timedelta(days=1),
            "author": "Jane Researcher",
            "image_url": "https://example.com/image.jpg",
            "quality_score": 85.0
        },
        {
            "title": "Global Tech Companies Report Strong Q4 Results",
            "description": "Tech sector shows resilience amid economic challenges",
            "content": "Major technology companies announced record earnings in the fourth quarter, defying economic predictions. The surge is attributed to increased cloud adoption and enterprise software spending.",
            "url": "https://example.com/earnings",
            "source": "BusinessToday",
            "published_at": datetime.utcnow() - timedelta(days=2),
            "author": "John Analyst",
            "image_url": "https://example.com/earnings.jpg",
            "quality_score": 78.0
        },
        {
            "title": "Quantum Computing Reaches New Milestone",
            "description": "Major tech company achieves error correction breakthrough",
            "content": "In a significant development for quantum computing, researchers have successfully implemented quantum error correction at scale. This achievement brings practical quantum computers closer to reality.",
            "url": "https://example.com/quantum",
            "source": "ScienceDaily",
            "published_at": datetime.utcnow() - timedelta(days=3),
            "author": "Dr. Sarah Lewis",
            "image_url": "https://example.com/quantum.jpg",
            "quality_score": 92.0
        }
    ]
    
    for article in articles:
        await mongodb.insert_one("articles", article)
    
    logger.info(f"✅ Created {len(articles)} sample articles")


async def seed_conversations():
    """Create sample conversations."""
    logger.info("Seeding conversations...")
    
    mongodb = await get_mongodb()
    
    # Get sample user
    users = await mongodb.find_many("users", limit=1)
    if not users:
        logger.warning("No users found, skipping conversations")
        return
    
    user_id = users[0].get("_id")
    
    conversations = [
        {
            "user_id": user_id,
            "messages": [
                {
                    "role": "user",
                    "content": "Tell me about the latest AI breakthroughs",
                    "timestamp": (datetime.utcnow() - timedelta(hours=2)).isoformat()
                },
                {
                    "role": "assistant",
                    "content": "Recent advances in AI have been remarkable. New models are more efficient and capable than ever before.",
                    "timestamp": (datetime.utcnow() - timedelta(hours=2)).isoformat()
                }
            ],
            "created_at": datetime.utcnow() - timedelta(hours=2),
            "updated_at": datetime.utcnow() - timedelta(hours=2),
            "metadata": {"topic": "ai", "message_count": 2}
        },
        {
            "user_id": user_id,
            "messages": [
                {
                    "role": "user",
                    "content": "What are the best tech stocks to watch?",
                    "timestamp": (datetime.utcnow() - timedelta(hours=1)).isoformat()
                },
                {
                    "role": "assistant",
                    "content": "Several tech giants have shown strong performance. I recommend researching companies in cloud computing and AI.",
                    "timestamp": (datetime.utcnow() - timedelta(hours=1)).isoformat()
                }
            ],
            "created_at": datetime.utcnow() - timedelta(hours=1),
            "updated_at": datetime.utcnow() - timedelta(hours=1),
            "metadata": {"topic": "finance", "message_count": 2}
        }
    ]
    
    for conv in conversations:
        await mongodb.insert_one("conversations", conv)
    
    logger.info(f"✅ Created {len(conversations)} sample conversations")


async def seed_posts():
    """Create sample social posts."""
    logger.info("Seeding posts...")
    
    mongodb = await get_mongodb()
    
    # Get sample user
    users = await mongodb.find_many("users", limit=1)
    if not users:
        logger.warning("No users found, skipping posts")
        return
    
    user_id = users[0].get("_id")
    
    posts = [
        {
            "user_id": user_id,
            "platform": "linkedin",
            "content": "Excited about the latest breakthroughs in AI! These advances will transform how we work.",
            "status": "published",
            "post_id": "li-123456",
            "url": "https://linkedin.com/feed/update/urn:li:activity:123456",
            "created_at": datetime.utcnow() - timedelta(days=1)
        },
        {
            "user_id": user_id,
            "platform": "twitter",
            "content": "🚀 AI innovation accelerating! Quantum breakthroughs coming in 2025 #AI #Technology",
            "status": "published",
            "post_id": "tw-789012",
            "url": "https://twitter.com/user/status/789012",
            "created_at": datetime.utcnow() - timedelta(days=1)
        }
    ]
    
    for post in posts:
        await mongodb.insert_one("posts", post)
    
    logger.info(f"✅ Created {len(posts)} sample posts")


async def clear_collections():
    """Clear all collections."""
    logger.info("Clearing collections...")
    
    mongodb = await get_mongodb()
    
    collections = ["users", "articles", "conversations", "posts", "migrations"]
    
    for collection in collections:
        try:
            await mongodb.client.delete_many(collection, {})
            logger.info(f"  Cleared {collection}")
        except:
            pass
    
    logger.info("✅ Collections cleared")


async def seed_database():
    """Seed all data."""
    logger.info("="*50)
    logger.info("Signal AI Database Seeding")
    logger.info("="*50)
    
    try:
        # Clear existing data
        await clear_collections()
        
        # Seed fresh data
        await seed_users()
        await seed_articles()
        await seed_conversations()
        await seed_posts()
        
        logger.info("="*50)
        logger.info("✅ Database seeding completed successfully")
        logger.info("="*50)
        
        return 0
    
    except Exception as e:
        logger.error(f"❌ Seeding error: {str(e)}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(seed_database())
    exit(exit_code)
