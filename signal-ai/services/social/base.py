
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class PostResult:
    """Standardized post result."""
    platform: str
    success: bool
    post_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None


class BaseSocialService(ABC):
    @abstractmethod
    async def create_post(
        self,
        content: str,
        access_token: Optional[str] = None,
        username: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a post on the platform."""
        pass

    @abstractmethod
    async def delete_post(
        self,
        post_id: str,
        access_token: Optional[str] = None,
        username: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delete a post."""
        pass