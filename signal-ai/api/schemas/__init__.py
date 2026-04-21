"""Request and response schemas."""
from api.schemas.request import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    ChatRequest,
    ChatResponse,
    ArticleSchema,
    NewsSearchRequest,
    NewsSearchResponse,
    SocialPostRequest,
    SocialPostResponse,
    PostResultSchema,
    UserSchema,
    SystemHealthSchema,
    OAuthCallbackRequest
)

__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "TokenResponse",
    "ChatRequest",
    "ChatResponse",
    "ArticleSchema",
    "NewsSearchRequest",
    "NewsSearchResponse",
    "SocialPostRequest",
    "SocialPostResponse",
    "PostResultSchema",
    "UserSchema",
    "SystemHealthSchema",
    "OAuthCallbackRequest"
]
