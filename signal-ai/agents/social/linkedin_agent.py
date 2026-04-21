import logging
from services.social.linkedin import LinkedInService

logger = logging.getLogger(__name__)

class LinkedInAgent:
    @staticmethod
    async def post(content: str) -> dict:
        """Post to LinkedIn and return result."""
        result = await LinkedInService.create_post(content)
        return result