from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


def _now_utc() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


class NewsArticle(BaseModel):
    title: str
    content: str
    source: str
    url: str
    date: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now_utc)


class UserQuery(BaseModel):
    query_text: str
    intent: str
    response: str
    user_id: Optional[str] = None   # NEW: associate query with authenticated user
    created_at: datetime = Field(default_factory=_now_utc)


class LinkedInPost(BaseModel):
    user_query_id: Optional[str] = None
    content: str
    linkedin_post_id: Optional[str] = None
    status: str  # "success" or "failed"
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=_now_utc)


# Optional: if you still want Summary (though not used in current agents)
class Summary(BaseModel):
    original_article_url: str
    summary_text: str
    created_at: datetime = Field(default_factory=_now_utc)