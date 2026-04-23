import logging
import asyncio
from services.queue.celery_app import celery_app
from agents.social.linkedin_agent import LinkedInAgent
from agents.social.facebook_agent import FacebookAgent
from agents.social.twitter_agent import TwitterAgent

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=3)
def post_to_linkedin_task(self, content: str, username: str):
    """Async task to post to LinkedIn with retries."""
    try:
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            LinkedInAgent.post(content, username=username)
        )
        if not result.get("success"):
            raise Exception(result.get("error", "Unknown error"))
        return result
    except Exception as exc:
        logger.error("LinkedIn post task failed: %s", exc)
        self.retry(exc=exc, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def post_to_facebook_task(self, content: str, username: str):
    """Async task to post to Facebook."""
    try:
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            FacebookAgent.post(content, username=username)
        )
        if not result.get("success"):
            raise Exception(result.get("error", "Unknown error"))
        return result
    except Exception as exc:
        logger.error("Facebook post task failed: %s", exc)
        self.retry(exc=exc, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def post_to_twitter_task(self, content: str, username: str):
    """Async task to post to Twitter."""
    try:
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            TwitterAgent.post(content, username=username)
        )
        if not result.get("success"):
            raise Exception(result.get("error", "Unknown error"))
        return result
    except Exception as exc:
        logger.error("Twitter post task failed: %s", exc)
        self.retry(exc=exc, countdown=60)

@celery_app.task
def summarize_news_task(article: dict):
    """Async summarization task."""
    from agents.summarizer.summarizer_agent import SummarizerAgent
    from services.llm.ollama import OllamaService
    loop = asyncio.get_event_loop()
    llm = OllamaService()
    summarizer = SummarizerAgent(llm)
    return loop.run_until_complete(summarizer.summarize(article))