import logging
from services.facebook_service import FacebookService

logger = logging.getLogger(__name__)

class FacebookAgent:
    @staticmethod
    async def post(content: str) -> dict:
        """Post to Facebook and return result."""
        result = await FacebookService.create_post(content)
        return result
