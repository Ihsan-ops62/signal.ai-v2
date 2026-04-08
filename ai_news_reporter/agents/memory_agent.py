import logging
from datetime import datetime, timezone
from typing import Optional

from database.mongodb_client import MongoDB
from database.models import UserQuery, NewsArticle, LinkedInPost

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    """Return current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class MemoryAgent:

    @staticmethod
    async def store_query(query: str, intent: str, response: str) -> Optional[str]:
        """Store a user query and return the inserted document ID (as a string)."""
        doc = UserQuery(
            query_text=query,
            intent=intent,
            response=response,
            created_at=_now_utc(),
        )
        try:
            # Run in background - don't block the workflow
            result = await MongoDB.get_collection("queries").insert_one(doc.model_dump())
            return str(result.inserted_id) if result else None
        except Exception as exc:
            logger.warning("Could not store query (non-fatal): %s", exc)
            # Return a dummy ID so workflow continues
            return None

    @staticmethod
    async def store_news_article(article: dict) -> None:
        """Persist a news article. Silently skips duplicates (E11000)."""
        doc = NewsArticle(
            title=article.get("title", ""),
            content=article.get("body", article.get("description", "")),
            source=article.get("source", article.get("url", "")),
            url=article.get("url", ""),
            date=article.get("date"),
            created_at=_now_utc(),
        )
        try:
            await MongoDB.get_collection("news").insert_one(doc.model_dump())
        except Exception as exc:
            # E11000 = duplicate key – article already stored, expected behaviour
            logger.debug(
                "Skipping duplicate news article %r: %s",
                article.get("title", "?"),
                exc,
            )

    @staticmethod
    async def store_post_result(
        query_id: Optional[str],
        content: str,
        linkedin_result: dict,
    ) -> None:
        """
        Persist the outcome of a LinkedIn post attempt.

        Uses update_one + upsert=True for successful posts so that
        re-running the workflow never creates duplicate records. Failed posts
        (post_id = None) are inserted directly to avoid null-key conflicts
        on a sparse unique index.
        """
        post_id = linkedin_result.get("post_id")
        status = "success" if linkedin_result.get("success") else "failed"

        doc = {
            "user_query_id": query_id,
            "content": content,
            "linkedin_post_id": post_id,
            "status": status,
            "error": linkedin_result.get("error"),
            "created_at": _now_utc(),
        }

        collection = MongoDB.get_collection("posts")

        try:
            if post_id:
                # Real post ID → safe unique key for upsert
                await collection.update_one(
                    {"linkedin_post_id": post_id},
                    {"$set": doc},
                    upsert=True,
                )
            else:
                # Failed post → drop the null ID field to avoid sparse-index conflict
                doc_no_null_id = {k: v for k, v in doc.items() if k != "linkedin_post_id"}
                await collection.insert_one(doc_no_null_id)

        except Exception as exc:
            logger.error("Failed to store post result (non-fatal): %s", exc)