import logging
from services.linkedin_service import LinkedInService

logger = logging.getLogger(__name__)


class LinkedInAgent:
    @staticmethod
    async def post(content: str, access_token: str = None, username: str = None) -> dict:
        """
        Post to LinkedIn and return result.

        Args:
            content:      The text content to post.
            access_token: Optional explicit token (overrides stored token).
            username:     The authenticated user's username — used to look up
                          their stored OAuth token from MongoDB.
        """
        result = await LinkedInService.create_post(
            content,
            access_token=access_token,
            username=username,
        )
        return result