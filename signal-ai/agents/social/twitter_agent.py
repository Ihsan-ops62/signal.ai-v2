import logging
from services.social.twitter import TwitterService

logger = logging.getLogger(__name__)


class TwitterAgent:

    @staticmethod
    async def post(
        content: str,
        access_token: str = None,
        username: str = None,
    ) -> dict:
        """
        Post a tweet and return the result dict.

        Args:
            content:      Text to tweet (auto-truncated to 280 chars if needed).
            access_token: Optional explicit OAuth 2.0 bearer token.
            username:     Authenticated user — used to look up the stored token.
        """
        result = await TwitterService.create_post(
            content,
            access_token=access_token,
            username=username,
        )
        return result

    @staticmethod
    async def delete(
        tweet_id: str,
        access_token: str = None,
        username: str = None,
    ) -> dict:
        """Delete a tweet by its ID."""
        result = await TwitterService.delete_post(
            tweet_id,
            access_token=access_token,
            username=username,
        )
        return result