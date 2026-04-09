import logging
from datetime import datetime, timezone
from typing import Optional

from database.mongodb_client import MongoDB
from database.models import UserQuery, NewsArticle

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
            result = await MongoDB.get_collection("queries").insert_one(doc.model_dump())
            return str(result.inserted_id) if result else None
        except Exception as exc:
            logger.warning("Could not store query (non-fatal): %s", exc)
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
        post_result: dict,
    ) -> None:
        """Persist the outcome of a social media post attempt.

        Works for both LinkedIn and Facebook. Uses ``platform_post_id`` as the
        deduplication key so re-running the workflow never creates duplicate
        records for the same live post.

        Args:
            query_id:    MongoDB ID of the originating user query.
            content:     The formatted post text that was (or was attempted to be) published.
            post_result: Dict returned by the posting agent — must include keys:
                         ``success`` (bool), ``post_id`` (str|None),
                         ``platform`` ('linkedin'|'facebook'), ``error`` (str|None).
        """
        post_id = post_result.get("post_id")
        platform = post_result.get("platform", "linkedin")
        status = "success" if post_result.get("success") else "failed"

        doc = {
            "user_query_id": query_id,
            "content": content,
            "platform": platform,               # NEW: track which network was used
            "platform_post_id": post_id,        # renamed from linkedin_post_id
            "status": status,
            "error": post_result.get("error"),
            "created_at": _now_utc(),
        }

        collection = MongoDB.get_collection("posts")

        try:
            if post_id:
                # Real post ID — safe unique key for upsert across both platforms
                await collection.update_one(
                    {"platform_post_id": post_id, "platform": platform},
                    {"$set": doc},
                    upsert=True,
                )
            else:
                # Failed post — drop null ID to avoid sparse-index conflict
                doc_no_null = {k: v for k, v in doc.items() if k != "platform_post_id"}
                await collection.insert_one(doc_no_null)

        except Exception as exc:
            logger.error("Failed to store post result (non-fatal): %s", exc)