
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends

from api.schemas.request import SystemHealthSchema
from api.dependencies.auth import get_current_user, require_admin
from api.dependencies.rate_limit import check_rate_limit
from services.llm.router import get_llm_router
from services.search.search_service import get_search_service
from infrastructure.database.mongodb import MongoDB
from services.cache.redis import get_cache
from infrastructure.messaging.kafka import get_kafka_producer
from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stats")
async def get_user_stats(current_user = Depends(get_current_user)):
    """Get statistics for the current user."""
    try:
        queries_coll = MongoDB.get_collection("queries")
        posts_coll = MongoDB.get_collection("posts")
        query_count = await queries_coll.count_documents({"user_id": current_user.sub})
        post_count = await posts_coll.count_documents({"user_id": current_user.sub, "status": "success"})
        li_posts = await posts_coll.count_documents({"user_id": current_user.sub, "platform": "linkedin", "status": "success"})
        fb_posts = await posts_coll.count_documents({"user_id": current_user.sub, "platform": "facebook", "status": "success"})
        tw_posts = await posts_coll.count_documents({"user_id": current_user.sub, "platform": "twitter", "status": "success"})
        return {
            "queries": query_count,
            "posts": post_count,
            "platforms": {"linkedin": li_posts, "facebook": fb_posts, "twitter": tw_posts},
        }
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get stats")


@router.get("/health", response_model=SystemHealthSchema)
async def system_health(
    admin_user = Depends(require_admin)
):
    """Get system health status."""
    try:
        results = {}
        
        # Check LLM
        try:
            llm = await get_llm_router()
            results["llm"] = await llm.health_check()
        except Exception as e:
            logger.warning(f"LLM health check failed: {str(e)}")
            results["llm"] = False
        
        # Check MongoDB (primary database)
        try:
            # Simple ping to MongoDB
            await MongoDB.get_collection("health").find_one({})
            results["database"] = True
        except Exception as e:
            logger.warning(f"Database health check failed: {str(e)}")
            results["database"] = False
        
        results["mongodb"] = results["database"]  # Same for now
        
        # Check Cache
        try:
            cache = await get_cache()
            results["cache"] = await cache.health_check()
        except Exception as e:
            logger.warning(f"Cache health check failed: {str(e)}")
            results["cache"] = False
        
        # Check Search (just assume if service exists)
        try:
            search = await get_search_service()
            results["search"] = search is not None
        except Exception:
            results["search"] = False
        
        # Check Queue (Kafka)
        try:
            producer = await get_kafka_producer()
            results["queue"] = producer is not None
        except Exception:
            results["queue"] = False
        
        healthy_count = sum(1 for v in results.values() if v)
        overall_healthy = healthy_count >= 4
        
        return SystemHealthSchema(
            status="healthy" if overall_healthy else "degraded",
            llm=results.get("llm", False),
            database=results.get("database", False),
            mongodb=results.get("mongodb", False),
            cache=results.get("cache", False),
            search=results.get("search", False),
            queue=results.get("queue", False),
            timestamp=datetime.utcnow()
        )
    
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Health check failed")


@router.get("/stats")
async def system_stats(
    admin_user = Depends(require_admin)
):
    """Get system statistics."""
    try:
        users_coll = MongoDB.get_collection("users")
        articles_coll = MongoDB.get_collection("articles")
        posts_coll = MongoDB.get_collection("posts")
        
        user_count = await users_coll.count_documents({})
        article_count = await articles_coll.count_documents({})
        post_count = await posts_coll.count_documents({})
        
        return {
            "users": {"total": user_count},
            "articles": {"total": article_count},
            "posts": {"total": post_count},
            "timestamp": datetime.utcnow()
        }
    
    except Exception as e:
        logger.error(f"Stats retrieval failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get stats")


@router.post("/cache/clear")
async def clear_cache(
    admin_user = Depends(require_admin)
):
    """Clear application cache."""
    try:
        cache = await get_cache()
        await cache.flush()
        return {"status": "success", "message": "Cache cleared"}
    except Exception as e:
        logger.error(f"Cache clear failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Cache clear failed")


@router.get("/config")
async def get_config(
    admin_user = Depends(require_admin)
):
    """Get application configuration (sanitized)."""
    try:
        return {
            "environment": settings.APP_ENV,
            "app_name": "Signal AI",
            "app_version": "1.0.0",
            "debug": settings.DEBUG,
            "features": {
                "llm": {
                    "primary": "ollama",
                    "fallback": "none"
                },
                "social_media": ["linkedin", "twitter", "facebook"],
                "news_sources": ["newsapi", "rss", "gnews"]
            }
        }
    except Exception as e:
        logger.error(f"Config retrieval failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Config retrieval failed")