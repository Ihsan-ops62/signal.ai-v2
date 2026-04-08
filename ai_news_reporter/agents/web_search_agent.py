import logging
import re
from services.search_service import SearchService

logger = logging.getLogger(__name__)

# Filler words to strip (common stopwords)
_STOPWORDS = re.compile(
    r"\b(go|and|the|a|an|to|for|on|in|of|is|it|this|that|me|my|"
    r"please|can|you|i|want|need|find|get|search|about|"
    r"summarize|summary|post|linkedin|format|write|tell|what|are|be|will|then|"
    r"latest|trend|news|article|please|kindly)\b",
    re.IGNORECASE,
)

# Always keep these short tech terms
_TECH_KEEP = {"ai", "ml", "dl", "llm", "gpt", "api", "gpu", "cpu", "vr", "ar", "iot", "saas", "cloud", "devops"}


class WebSearchAgent:

    @staticmethod
    def _build_search_query(user_query: str) -> str:
        """
        Convert natural language to a search query that emphasizes tech news.
        """
        # Remove stopwords
        cleaned = _STOPWORDS.sub("", user_query)
        # Remove punctuation
        cleaned = re.sub(r"[,\.!?;:]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        
        # Split into meaningful words
        words = []
        for w in cleaned.split():
            if len(w) > 2 or w.lower() in _TECH_KEEP:
                words.append(w)
        
        # If we lost everything, use a generic tech query
        if not words:
            words = ["technology", "news"]
        
        # Take up to 5 words, ensure "tech" or "technology" if missing
        short_query = " ".join(words[:5])
        if "tech" not in short_query.lower() and "technology" not in short_query.lower():
            short_query += " technology"
        
        logger.info("Tech search query: '%s' → '%s'", user_query[:60], short_query)
        return short_query

    @staticmethod
    async def search(query: str, max_results: int = 5) -> list:
        """Search for tech news using the cleaned query."""
        short_query = WebSearchAgent._build_search_query(query)
        results = await SearchService.search_news(short_query, max_results)
        logger.info("Found %d tech results", len(results))
        return results