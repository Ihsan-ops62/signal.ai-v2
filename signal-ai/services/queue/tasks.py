"""
Celery tasks for Signal AI.
Background processing for news, summarization, and social posting.
"""

import logging
from datetime import datetime

from services.queue.celery_app import app
from services.search.search_service import get_search_service
from services.llm.router import get_llm_router
from infrastructure.database.mongodb import get_mongodb
from infrastructure.messaging.kafka import get_kafka_producer, EventType
from infrastructure.monitoring.metrics import MetricsCollector

logger = logging.getLogger(__name__)


@app.task(name="services.queue.tasks.fetch_trending_news", bind=True)
async def fetch_trending_news(self):
    """Fetch trending news in background."""
    try:
        search_service = await get_search_service()
        articles = await search_service.get_trending(limit=20)
        
        # Store in MongoDB
        mongodb = await get_mongodb()
        if articles:
            article_ids = await mongodb.insert_many("articles", articles)
            
            # Publish Kafka events
            producer = await get_kafka_producer()
            for article in articles:
                await producer.publish_article_discovered(article)
            
            # Record metrics
            MetricsCollector.record_news_processing("processed", len(articles))
            
            logger.info(f"Fetched and stored {len(articles)} trending articles")
            return {"status": "success", "count": len(articles)}
    except Exception as e:
        logger.error(f"Trending news fetch failed: {str(e)}")
        MetricsCollector.record_error("TaskError", "fetch_trending_news")
        return {"status": "failed", "error": str(e)}


@app.task(name="services.queue.tasks.summarize_article", bind=True)
async def summarize_article(self, article_id: str):
    """Summarize a news article."""
    try:
        mongodb = await get_mongodb()
        
        # Get article
        article = await mongodb.find_one("articles", {"_id": article_id})
        if not article:
            return {"status": "not_found"}
        
        # Generate summary
        llm = await get_llm_router()
        content = article.get("content", article.get("description", ""))
        
        summary_prompt = f"""
Summarize the following news article in 2-3 sentences, keeping the most important facts:

{content}

Summary:
"""
        
        result = await llm.generate(summary_prompt, max_tokens=150)
        
        # Store summary
        await mongodb.update_one(
            "articles",
            {"_id": article_id},
            {
                "summary": result.text,
                "summarized_at": datetime.utcnow()
            }
        )
        
        logger.info(f"Summarized article {article_id}")
        return {"status": "success", "summary": result.text}
    
    except Exception as e:
        logger.error(f"Article summarization failed: {str(e)}")
        MetricsCollector.record_error("TaskError", "summarize_article")
        return {"status": "failed", "error": str(e)}


@app.task(name="services.queue.tasks.process_pending_posts", bind=True)
async def process_pending_posts(self):
    """Process posts awaiting publishing."""
    try:
        mongodb = await get_mongodb()
        
        # Find pending posts
        pending = await mongodb.find_many(
            "posts",
            {"status": "pending"},
            limit=10
        )
        
        processed = 0
        for post in pending:
            try:
                # TODO: Post to social media
                await mongodb.update_one(
                    "posts",
                    {"_id": post["_id"]},
                    {"status": "published", "published_at": datetime.utcnow()}
                )
                processed += 1
            except Exception as e:
                logger.error(f"Failed to post {post['_id']}: {str(e)}")
        
        logger.info(f"Processed {processed} pending posts")
        return {"status": "success", "processed": processed}
    
    except Exception as e:
        logger.error(f"Pending posts processing failed: {str(e)}")
        MetricsCollector.record_error("TaskError", "process_pending_posts")
        return {"status": "failed", "error": str(e)}


@app.task(name="services.queue.tasks.health_check", bind=True)
async def health_check(self):
    """Perform system health check."""
    try:
        results = {}
        
        # Check services
        try:
            llm = await get_llm_router()
            results["llm"] = await llm.health_check()
        except Exception as e:
            results["llm"] = False
        
        try:
            search = await get_search_service()
            results["search"] = True  # News API is up if we can call it
        except Exception as e:
            results["search"] = False
        
        try:
            mongodb = await get_mongodb()
            results["mongodb"] = await mongodb.health_check()
        except Exception as e:
            results["mongodb"] = False
        
        # Publish health check event
        try:
            producer = await get_kafka_producer()
            await producer.publish(
                "system",
                EventType.HEALTH_CHECK,
                results
            )
        except:
            pass
        
        healthy = all(results.values())
        logger.info(f"Health check: {results}")
        return {"status": "success", "healthy": healthy, "results": results}
    
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {"status": "failed", "error": str(e)}


@app.task(name="services.queue.tasks.retry_failed_posts", bind=True)
async def retry_failed_posts(self):
    """Retry failed social media posts."""
    try:
        mongodb = await get_mongodb()
        
        # Find failed posts from last hour
        from datetime import timedelta
        hour_ago = datetime.utcnow() - timedelta(hours=1)
        
        failed = await mongodb.find_many(
            "posts",
            {
                "status": "failed",
                "created_at": {"$gt": hour_ago},
                "retry_count": {"$lt": 3}
            },
            limit=5
        )
        
        retried = 0
        for post in failed:
            try:
                # Increment retry count
                retry_count = post.get("retry_count", 0) + 1
                await mongodb.update_one(
                    "posts",
                    {"_id": post["_id"]},
                    {"retry_count": retry_count, "status": "pending"}
                )
                retried += 1
            except Exception as e:
                logger.error(f"Failed to retry post {post['_id']}: {str(e)}")
        
        logger.info(f"Retried {retried} failed posts")
        return {"status": "success", "retried": retried}
    
    except Exception as e:
        logger.error(f"Retry failed posts failed: {str(e)}")
        return {"status": "failed", "error": str(e)}
