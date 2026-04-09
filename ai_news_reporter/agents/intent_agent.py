import logging
import re

from services.ollama_service import OllamaService

logger = logging.getLogger(__name__)

_VALID_INTENTS = frozenset({"news_query", "post_request", "news_then_post", "other"})

# Strips surrounding quotes, backticks, punctuation, and whitespace from LLM output
_CLEAN_RE = re.compile(r'[\s"\'`.,;:]+')

# Word-boundary pattern — prevents "fb" matching "feedback", "buffer", etc.
_FACEBOOK_RE = re.compile(r'\b(facebook|fb)\b', re.IGNORECASE)


class IntentAgent:
    """Classifies a user query into one of four intent categories."""

    def __init__(self, llm_service: OllamaService) -> None:
        self.llm = llm_service

    async def classify(self, query: str) -> str:
        """Return the intent category for *query*.

        Categories:
            - ``news_query``    – user wants to read tech news.
            - ``post_request``  – user wants to post to LinkedIn or Facebook directly.
            - ``news_then_post``– user wants news fetched, summarised, then posted.
            - ``other``         – anything else.
        """
        prompt = f"""You are an intent classifier. Classify the user's request into exactly one of these categories:

- news_query      : user asks for latest tech news only (e.g. "What is the latest news in AI?")
- post_request    : user asks to post something on LinkedIn or Facebook (e.g. "Post this to Facebook")
- news_then_post  : user wants news searched, summarized, then posted (e.g. "Find ML news and post on Facebook")
- other           : anything else

User query: "{query}"

Rules:
1. Reply with ONLY the category name – no punctuation, no quotes, no explanation.
2. If unsure, reply: other
"""
        raw = await self.llm.generate(prompt, temperature=0.1)

        # Normalise: strip whitespace, quotes, punctuation, lowercase
        intent = _CLEAN_RE.sub("", raw).lower()

        # The LLM sometimes returns the category inside a longer phrase —
        # try to extract a known intent token if exact match fails.
        if intent not in _VALID_INTENTS:
            for candidate in _VALID_INTENTS:
                if candidate in raw.lower():
                    intent = candidate
                    break
            else:
                logger.warning("Unrecognised intent %r from LLM – defaulting to 'other'", raw)
                intent = "other"

        logger.info("Classified intent: %r → %r", query[:60], intent)
        return intent

    def detect_platform(self, query: str) -> str:
        """Detect which social platform the user wants to post to.

        Uses a word-boundary regex to avoid false positives such as
        "feedback", "buffer", or "combat" matching "fb" or "face".

        Returns:
            - ``'facebook'`` if the query explicitly mentions Facebook or the
              abbreviation ``fb`` as a standalone word.
            - ``'linkedin'`` otherwise (safe default).
        """
        if _FACEBOOK_RE.search(query):
            logger.info("Detected platform: Facebook")
            return "facebook"
        logger.info("Detected platform: LinkedIn (default)")
        return "linkedin"