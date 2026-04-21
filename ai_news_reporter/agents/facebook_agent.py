"""
agents/facebook_agent.py
─────────────────────────
Thin agent wrapper around FacebookService — mirrors LinkedInAgent.
"""
import logging
from services.facebook_service import FacebookService

logger = logging.getLogger(__name__)


class FacebookAgent:

    @staticmethod
    async def post(
        content: str,
        access_token: str = None,
        page_id: str = None,
        username: str = None,
    ) -> dict:
        """
        Post to a Facebook Page and return the result dict.

        Args:
            content:      Text to post.
            access_token: Optional explicit Page Access Token.
            page_id:      Optional explicit Page ID (required if token is explicit).
            username:     Authenticated user — used to look up stored token + page_id.
        """
        result = await FacebookService.create_post(
            content,
            access_token=access_token,
            page_id=page_id,
            username=username,
        )
        return result