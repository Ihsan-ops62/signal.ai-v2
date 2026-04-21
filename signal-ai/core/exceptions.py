"""core/exceptions.py – Custom exception classes."""


class SignalBaseException(Exception):
    """Base exception for Signal AI."""
    pass


class AuthenticationError(SignalBaseException):
    """Raised when authentication fails."""
    pass


class RateLimitError(SignalBaseException):
    """Raised when rate limit is exceeded."""
    pass


class ServiceUnavailableError(SignalBaseException):
    """Raised when a required service is unavailable."""
    pass


class TokenExpiredError(SignalBaseException):
    """Raised when OAuth token is expired."""
    pass


class CacheError(SignalBaseException):
    """Raised when a cache operation fails."""
    pass


class LLMError(SignalBaseException):
    """Raised when LLM service fails."""
    pass


class SearchError(SignalBaseException):
    """Raised when news search fails."""
    pass


class SocialMediaError(SignalBaseException):
    """Raised when social media posting fails."""
    pass


class ExternalServiceError(SignalBaseException):
    """Raised when an external service call fails."""
    def __init__(self, service: str, message: str):
        self.service = service
        self.message = message
        super().__init__(f"{service}: {message}")