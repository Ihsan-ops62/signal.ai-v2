import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from infrastructure.database.mongodb import MongoDB

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class MemoryAgent:

    @staticmethod
    async def store_query(
        query: str, intent: str, response: str, user_id: Optional[str] = None
    ) -> Optional[str]:
        doc = {
            "query_text": query,
            "intent": intent,
            "response": response,
            "user_id": user_id,
            "created_at": _now_utc(),
        }
        try:
            result = await MongoDB.get_collection("queries").insert_one(doc)
            return str(result.inserted_id) if result else None
        except Exception as exc:
            logger.warning("Could not store query (non-fatal): %s", exc)
            return None

    @staticmethod
    async def store_news_article(article: dict) -> None:
        doc = {
            "title": article.get("title", ""),
            "content": article.get("body", article.get("description", "")),
            "source": article.get("source", article.get("url", "")),
            "url": article.get("url", ""),
            "date": article.get("date"),
            "created_at": _now_utc(),
        }
        try:
            await MongoDB.get_collection("news").insert_one(doc)
        except Exception as exc:
            logger.debug("Skipping duplicate news article %r: %s", article.get("title", "?"), exc)

    @staticmethod
    async def store_post_result(
        query_id: Optional[str],
        content: str,
        post_result: dict,
        user_id: Optional[str] = None,
    ) -> None:
        post_id = post_result.get("post_id")
        platform = post_result.get("platform", "linkedin")
        status = "success" if post_result.get("success") else "failed"
        doc = {
            "user_query_id": query_id,
            "content": content,
            "platform": platform,
            "platform_post_id": post_id,
            "status": status,
            "error": post_result.get("error"),
            "created_at": _now_utc(),
            "user_id": user_id,
        }
        collection = MongoDB.get_collection("posts")
        try:
            if post_id:
                await collection.update_one(
                    {"platform_post_id": post_id, "platform": platform},
                    {"$set": doc},
                    upsert=True,
                )
            else:
                doc_no_null = {k: v for k, v in doc.items() if k != "platform_post_id"}
                await collection.insert_one(doc_no_null)
        except Exception as exc:
            logger.error("Failed to store post result (non-fatal): %s", exc)

    @staticmethod
    async def save_session(session_id: str, pending_data: Dict[str, Any]) -> None:
        collection = MongoDB.get_collection("sessions")
        doc = {
            "session_id": session_id,
            "pending_data": pending_data,
            "updated_at": _now_utc(),
        }
        try:
            await collection.update_one(
                {"session_id": session_id},
                {"$set": doc},
                upsert=True,
            )
        except Exception as exc:
            logger.error("Failed to save session %s: %s", session_id, exc)

    @staticmethod
    async def load_session(session_id: str) -> Optional[Dict[str, Any]]:
        collection = MongoDB.get_collection("sessions")
        doc = await collection.find_one({"session_id": session_id})
        if doc:
            return doc.get("pending_data")
        return None

    @staticmethod
    async def delete_session(session_id: str) -> None:
        collection = MongoDB.get_collection("sessions")
        try:
            await collection.delete_one({"session_id": session_id})
        except Exception as exc:
            logger.error("Failed to delete session %s: %s", session_id, exc)

    @staticmethod
    async def save_context(session_id: str, context_history: List[Dict], user_id: Optional[str] = None) -> None:
        collection = MongoDB.get_collection("contexts")
        doc = {
            "session_id": session_id,
            "user_id": user_id,
            "history": context_history,
            "updated_at": _now_utc(),
        }
        try:
            await collection.update_one(
                {"session_id": session_id},
                {"$set": doc},
                upsert=True,
            )
        except Exception as exc:
            logger.error("Failed to save context for session %s: %s", session_id, exc)

    @staticmethod
    async def load_context(session_id: str) -> List[Dict]:
        collection = MongoDB.get_collection("contexts")
        doc = await collection.find_one({"session_id": session_id})
        if doc:
            return doc.get("history", [])
        return []

    @staticmethod
    async def get_recent_activities(user_id: Optional[str] = None, limit: int = 20) -> List[Dict]:
        queries_coll = MongoDB.get_collection("queries")
        posts_coll = MongoDB.get_collection("posts")
        query_filter = {"user_id": user_id} if user_id else {}
        post_filter = {"user_id": user_id} if user_id else {}
        queries = await queries_coll.find(query_filter).sort("created_at", -1).limit(limit).to_list(limit)
        posts = await posts_coll.find(post_filter).sort("created_at", -1).limit(limit).to_list(limit)
        activities = []
        for q in queries:
            activities.append({
                "type": "query",
                "timestamp": q.get("created_at"),
                "text": q.get("query_text", "")[:100],
                "intent": q.get("intent"),
            })
        for p in posts:
            activities.append({
                "type": "post",
                "timestamp": p.get("created_at"),
                "platform": p.get("platform"),
                "status": p.get("status"),
                "content_preview": p.get("content", "")[:100],
            })
        activities.sort(key=lambda x: x["timestamp"] if x["timestamp"] else _now_utc(), reverse=True)
        return activities[:limit]