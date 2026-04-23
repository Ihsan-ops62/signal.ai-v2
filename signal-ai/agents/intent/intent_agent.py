import logging
import re
from typing import List

from services.llm.ollama import OllamaService

logger = logging.getLogger(__name__)

_VALID_INTENTS = frozenset({"news_query", "post_request", "news_then_post", "other"})
_CLEAN_RE      = re.compile(r'[\s"\'`.,;:]+')
_FACEBOOK_RE   = re.compile(r'\b(facebook|fb)\b', re.IGNORECASE)
_LINKEDIN_RE   = re.compile(r'\b(linkedin|linked in)\b', re.IGNORECASE)
_TWITTER_RE    = re.compile(r'\b(twitter|tweet)\b', re.IGNORECASE)

# Expanded keyword sets for heuristic
_SEARCH_KEYWORDS = {"search", "find", "fetch", "look up", "get", "show", "tell", "what is", "latest", "news", "update", "headline", "article", "story", "trend", "recent"}
_POST_KEYWORDS   = {"post", "share", "publish", "upload", "send", "tweet"}


class IntentAgent:
    def __init__(self, llm_service: OllamaService) -> None:
        self.llm = llm_service

    async def classify(self, query: str) -> str:
        """Return intent: news_query | post_request | news_then_post | other."""
        q_lower = query.lower()

        has_search = any(kw in q_lower for kw in _SEARCH_KEYWORDS)
        has_post   = any(kw in q_lower for kw in _POST_KEYWORDS)

        # Strong heuristic: if both search and post keywords appear, it's news_then_post
        if has_search and has_post:
            logger.info("Heuristic: both search and post keywords → news_then_post")
            return "news_then_post"

        # Use LLM for fine-grained classification only when ambiguous
        prompt = f"""You are an intent classifier. Classify the user's request into exactly one category:

- news_query      : user ONLY wants to hear/read recent tech news. No mention of posting.
- post_request    : user wants to publish specific content to social media (they provide the content).
- news_then_post  : user explicitly asks to BOTH search for news AND post it to social media.
- other           : anything else — chat, questions about the bot, jokes, etc.

Examples:
"What's new in AI?" → news_query
"Latest machine learning news" → news_query
"Find ML news" → news_query
"Post this to LinkedIn: Hello world" → post_request
"Share on Facebook: Check this out" → post_request
"Find AI news and post it to LinkedIn" → news_then_post
"Search ML news and share on Facebook" → news_then_post
"Search ML news and share on Twitter" → news_then_post
"Tell me about yourself" → other
"How are you?" → other
"Hi" → other

User query: "{query}"

Reply with ONLY the category name — no punctuation, no explanation.
"""
        raw = await self.llm.generate(prompt, temperature=0.1)
        intent = _CLEAN_RE.sub("", raw).lower()

        if intent not in _VALID_INTENTS:
            for candidate in _VALID_INTENTS:
                if candidate in raw.lower():
                    intent = candidate
                    break
            else:
                logger.warning("Unrecognised intent %r → default 'other'", raw)
                intent = "other"

        logger.info("Classified intent: %r → %r", query[:60], intent)
        return intent

    def detect_platforms(self, query: str) -> List[str]:
        """Return list of platforms mentioned: 'linkedin', 'facebook', 'twitter'."""
        platforms = []
        if _LINKEDIN_RE.search(query):
            platforms.append("linkedin")
        if _FACEBOOK_RE.search(query):
            platforms.append("facebook")
        if _TWITTER_RE.search(query):
            platforms.append("twitter")
        if not platforms:
            platforms.append("linkedin")  # default
        logger.debug("Detected platforms for '%s': %s", query[:50], platforms)
        return platforms

    # Legacy method (kept for compatibility)
    def detect_platform(self, query: str) -> str:
        platforms = self.detect_platforms(query)
        if len(platforms) > 1:
            return "both"
        return platforms[0]