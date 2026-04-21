"""
Chat routes for Signal AI.
Handles conversational queries and news requests.
"""

import logging
from datetime import datetime
from bson import ObjectId

from fastapi import APIRouter, HTTPException, Depends

from api.schemas.request import ChatRequest, ChatResponse, NewsSearchRequest, NewsSearchResponse, ArticleSchema
from api.dependencies.auth import get_current_user
from api.dependencies.rate_limit import check_rate_limit
from services.llm.router import get_llm_router
from services.search.search_service import get_search_service
from infrastructure.database.mongodb import MongoDB
from infrastructure.monitoring.metrics import MetricsCollector, MetricsContext

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/search-news", response_model=NewsSearchResponse)
async def search_news(
    request: NewsSearchRequest,
    current_user = Depends(get_current_user),
    _: None = Depends(check_rate_limit)
):
    """Search for news articles."""
    try:
        with MetricsContext("agent_execution", agent="search", service="chat"):
            search_service = await get_search_service()
            articles = await search_service.search(
                query=request.query,
                category=request.category,
                limit=request.limit
            )
            article_schemas = [ArticleSchema(**a) for a in articles]
            return NewsSearchResponse(
                articles=article_schemas,
                total=len(articles),
                timestamp=datetime.utcnow()
            )
    except Exception as e:
        logger.error(f"News search failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Search failed")


@router.get("/trending-news", response_model=NewsSearchResponse)
async def get_trending_news(
    limit: int = 10,
    current_user = Depends(get_current_user),
    _: None = Depends(check_rate_limit)
):
    """Get trending news."""
    try:
        search_service = await get_search_service()
        articles = await search_service.get_trending(limit=limit)
        article_schemas = [ArticleSchema(**a) for a in articles]
        return NewsSearchResponse(
            articles=article_schemas,
            total=len(articles),
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        logger.error(f"Trending fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch trending news")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user = Depends(get_current_user),
    _: None = Depends(check_rate_limit)
):
    """Send chat message and get response."""
    try:
        with MetricsContext("agent_execution", agent="conversation", service="chat"):
            llm = await get_llm_router()
            system_prompt = "You are a helpful AI news reporter assistant. Help users find, summarize, and share news."
            full_prompt = f"{system_prompt}\n\nUser: {request.message}\nAssistant:"
            response_text = await llm.generate(full_prompt, temperature=0.7)

            conv_coll = MongoDB.get_collection("conversations")
            if request.conversation_id:
                await conv_coll.update_one(
                    {"_id": ObjectId(request.conversation_id)},
                    {
                        "$push": {
                            "messages": [
                                {"role": "user", "content": request.message},
                                {"role": "assistant", "content": response_text}
                            ]
                        },
                        "$set": {"updated_at": datetime.utcnow()}
                    }
                )
                conv_id = request.conversation_id
            else:
                result = await conv_coll.insert_one({
                    "user_id": current_user.sub,
                    "messages": [
                        {"role": "user", "content": request.message},
                        {"role": "assistant", "content": response_text}
                    ],
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })
                conv_id = str(result.inserted_id)

            return ChatResponse(
                response=response_text,
                conversation_id=conv_id,
                timestamp=datetime.utcnow()
            )
    except Exception as e:
        logger.error(f"Chat failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Chat failed")


@router.get("/sessions")
async def list_sessions(current_user = Depends(get_current_user)):
    """List user's conversation sessions."""
    try:
        conv_coll = MongoDB.get_collection("conversations")
        cursor = conv_coll.find({"user_id": current_user.sub}).sort("updated_at", -1).limit(30)
        sessions = []
        async for doc in cursor:
            preview = ""
            messages = doc.get("messages", [])
            if messages:
                first_user_msg = next((m for m in messages if m.get("role") == "user"), None)
                if first_user_msg:
                    preview = first_user_msg.get("content", "")[:50]
            sessions.append({
                "session_id": str(doc["_id"]),
                "preview": preview,
                "updated_at": doc.get("updated_at", doc.get("created_at")).isoformat()
            })
        return {"sessions": sessions}
    except Exception as e:
        logger.error(f"Failed to list sessions: {e}")
        raise HTTPException(status_code=500, detail="Failed to list sessions")


@router.get("/session/{session_id}")
async def get_session(session_id: str, current_user = Depends(get_current_user)):
    """Get a specific conversation session."""
    try:
        conv_coll = MongoDB.get_collection("conversations")
        doc = await conv_coll.find_one({"_id": ObjectId(session_id), "user_id": current_user.sub})
        if not doc:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "session_id": session_id,
            "messages": doc.get("messages", [])
        }
    except Exception as e:
        logger.error(f"Failed to get session: {e}")
        raise HTTPException(status_code=500, detail="Failed to get session")


@router.delete("/session/{session_id}")
async def delete_session(session_id: str, current_user = Depends(get_current_user)):
    """Delete a conversation session."""
    try:
        conv_coll = MongoDB.get_collection("conversations")
        result = await conv_coll.delete_one({"_id": ObjectId(session_id), "user_id": current_user.sub})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Failed to delete session: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete session")


# NEW: User stats endpoint (non-admin)
@router.get("/stats")
async def get_user_stats(current_user = Depends(get_current_user)):
    """Get statistics for the current user."""
    try:
        queries_coll = MongoDB.get_collection("queries")
        posts_coll = MongoDB.get_collection("posts")
        query_count = await queries_coll.count_documents({"user_id": current_user.sub})
        post_count = await posts_coll.count_documents({"user_id": current_user.sub, "status": "success"})
        # Optional platform breakdown
        li_posts = await posts_coll.count_documents({"user_id": current_user.sub, "platform": "linkedin", "status": "success"})
        fb_posts = await posts_coll.count_documents({"user_id": current_user.sub, "platform": "facebook", "status": "success"})
        tw_posts = await posts_coll.count_documents({"user_id": current_user.sub, "platform": "twitter", "status": "success"})
        return {
            "queries": query_count,
            "posts": post_count,
            "platforms": {"linkedin": li_posts, "facebook": fb_posts, "twitter": tw_posts}
        }
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get stats")