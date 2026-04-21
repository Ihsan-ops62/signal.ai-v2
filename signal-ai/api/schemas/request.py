"""
API request and response schemas for Signal AI.
Pydantic models for data validation.
"""

from pydantic import BaseModel, Field, EmailStr, validator
from typing import Optional, List
from datetime import datetime


# Auth Schemas
class RegisterRequest(BaseModel):
    """User registration request."""
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=2)


class LoginRequest(BaseModel):
    """User login request."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Token response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


# Chat Schemas
class ChatRequest(BaseModel):
    """Chat request."""
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Chat response."""
    response: str
    conversation_id: str
    timestamp: datetime


# News Schemas
class ArticleSchema(BaseModel):
    """News article schema."""
    title: str
    description: str
    content: Optional[str] = None
    url: str
    source: str
    published_at: datetime
    author: Optional[str] = None
    image_url: Optional[str] = None
    summary: Optional[str] = None
    quality_score: Optional[float] = None


class NewsSearchRequest(BaseModel):
    """News search request."""
    query: str = Field(..., min_length=3, max_length=200)
    category: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=50)


class NewsSearchResponse(BaseModel):
    """News search response."""
    articles: List[ArticleSchema]
    total: int
    timestamp: datetime


# Social Media Schemas
class SocialPostRequest(BaseModel):
    """Social media post request."""
    content: str = Field(..., min_length=10, max_length=5000)
    platforms: List[str] = Field(default=["linkedin", "twitter", "facebook"])
    media_urls: Optional[List[str]] = None
    schedule_time: Optional[datetime] = None


class PostResultSchema(BaseModel):
    """Social media post result."""
    platform: str
    post_id: str
    url: str
    status: str
    error: Optional[str] = None


class SocialPostResponse(BaseModel):
    """Social media post response."""
    results: List[PostResultSchema]
    timestamp: datetime


class OAuthCallbackRequest(BaseModel):
    """OAuth callback request."""
    code: str
    state: str
    platform: str


# User Schemas
class UserSchema(BaseModel):
    """User schema."""
    id: str
    email: str
    name: str
    created_at: datetime
    linkedin_connected: bool = False
    twitter_connected: bool = False
    facebook_connected: bool = False


class UserPreferencesSchema(BaseModel):
    """User preferences schema."""
    tone: str = Field(default="professional", pattern="^(professional|casual|technical)$")
    platforms: List[str] = Field(default=["linkedin"])
    categories: List[str] = Field(default=["technology"])
    auto_post: bool = False
    post_frequency: Optional[str] = None


# Admin Schemas
class SystemHealthSchema(BaseModel):
    """System health schema."""
    status: str
    llm: bool
    database: bool
    cache: bool
    search: bool
    queue: bool
    timestamp: datetime


class MetricsSnapshot(BaseModel):
    """Metrics snapshot."""
    requests_total: int
    errors_total: int
    articles_processed: int
    posts_published: int
    active_users: int
    timestamp: datetime


# Error Schemas
class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    message: str
    details: Optional[dict] = None

# Admin Schemas
class SystemHealthSchema(BaseModel):
    """System health schema."""
    status: str
    llm: bool
    database: bool
    mongodb: bool
    cache: bool
    search: bool
    queue: bool
    timestamp: datetime