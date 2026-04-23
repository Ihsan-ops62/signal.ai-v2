class SignalAIException(Exception):
    """Base exception for Signal.AI"""
    def __init__(self, message: str, code: str = "SIGNAL_ERROR", status_code: int = 500):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(self.message)


# ─── AUTHENTICATION & SECURITY ───
class AuthenticationError(SignalAIException):
    """Authentication/authorization failed"""
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, "AUTH_ERROR", 401)


class TokenExpiredError(SignalAIException):
    """OAuth token expired or invalid"""
    def __init__(self, message: str = "Token expired", platform: str = None):
        self.platform = platform
        super().__init__(message, "TOKEN_EXPIRED", 401)


class PermissionDeniedError(SignalAIException):
    """User lacks permission"""
    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, "PERMISSION_DENIED", 403)


# ─── VALIDATION & INPUT ───
class ValidationError(SignalAIException):
    """Input validation failed"""
    def __init__(self, message: str, field: str = None):
        self.field = field
        super().__init__(message, "VALIDATION_ERROR", 400)


# ─── POSTING & SOCIAL MEDIA ───
class PostingError(SignalAIException):
    """Social media posting failed"""
    def __init__(self, message: str, platform: str = None):
        self.platform = platform
        super().__init__(message, "POSTING_ERROR", 400)


class DuplicateContentError(PostingError):
    """Content was already posted recently"""
    def __init__(self, message: str = "This content was already posted recently", platform: str = None):
        super().__init__(message, platform)
        self.code = "DUPLICATE_CONTENT"


class RateLimitError(PostingError):
    """Rate limit exceeded for posting"""
    def __init__(self, message: str = "Rate limit exceeded", platform: str = None, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(message, platform)
        self.code = "RATE_LIMIT"
        self.status_code = 429


class SocialMediaAPIError(PostingError):
    """Social media API error (LinkedIn, Facebook, Twitter)"""
    def __init__(self, message: str, platform: str = None, status_code: int = None):
        super().__init__(message, platform)
        self.code = "SOCIAL_MEDIA_API_ERROR"
        if status_code:
            self.status_code = status_code


# ─── SEARCH & NEWS ───
class SearchError(SignalAIException):
    """Search/news API error"""
    def __init__(self, message: str = "Search failed"):
        super().__init__(message, "SEARCH_ERROR", 500)


# ─── LLM & LANGUAGE MODEL ───
class LLMError(SignalAIException):
    """LLM/Ollama error"""
    def __init__(self, message: str = "LLM service error"):
        super().__init__(message, "LLM_ERROR", 503)


class LLMTimeoutError(LLMError):
    """LLM request timed out"""
    def __init__(self, message: str = "LLM request timed out"):
        super().__init__(message)
        self.code = "LLM_TIMEOUT"


# ─── DATABASE ───
class DatabaseError(SignalAIException):
    """MongoDB error"""
    def __init__(self, message: str = "Database error"):
        super().__init__(message, "DATABASE_ERROR", 500)


# ─── EXTERNAL SERVICES ───
class ExternalServiceError(SignalAIException):
    """External service call failed"""
    def __init__(self, service: str, message: str):
        self.service = service
        self.message = message
        super().__init__(f"{service}: {message}", "EXTERNAL_SERVICE_ERROR", 502)