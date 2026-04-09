import logging
import re
from services.search_service import SearchService

logger = logging.getLogger(__name__)

# Stopwords to remove (Added "linked in", "facebook", "trending", "today", etc.)
_STOPWORDS = re.compile(
    r"\b(go|and|the|a|an|to|for|on|in|of|is|it|this|that|me|my|"
    r"please|can|you|i|want|need|find|get|search|about|"
    r"summarize|summary|post|linkedin|linked in|facebook|fb|format|write|tell|what|are|be|will|then|"
    r"latest|trending|trend|news|article|please|kindly|today|now)\b",
    re.IGNORECASE,
)

# Always keep short tech terms (Added python and others just to be safe)
_TECH_KEEP = {
    "ai", "ml", "dl", "llm", "gpt", "api", "gpu", "cpu", "vr", "ar", "iot", 
    "saas", "cloud", "devops", "python", "java", "rust", "sql"
}


class WebSearchAgent:

    @staticmethod
    def _build_search_query(user_query: str) -> str:
        """
        Convert natural language to a search query that emphasizes tech news.
        Special handling for "ML news" -> "machine learning news"
        """
        # Replace common abbreviations
        query = user_query.lower()
        query = re.sub(r'\bml\b', 'machine learning', query)
        query = re.sub(r'\bai\b', 'artificial intelligence', query)
        query = re.sub(r'\bllm\b', 'large language model', query)
        
        # Remove stopwords
        cleaned = _STOPWORDS.sub("", query)
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
        
        # Take up to 6 words, ensure "tech" or "technology" if missing
        short_query = " ".join(words[:6])
        if "tech" not in short_query.lower() and "technology" not in short_query.lower():
            short_query += " technology news"
        
        logger.info("Tech search query: '%s' → '%s'", user_query[:60], short_query)
        return short_query

    @staticmethod
    async def search(query: str, max_results: int = 5) -> list:
        """Search for tech news using the cleaned query."""
        short_query = WebSearchAgent._build_search_query(query)
        results = await SearchService.search_news(short_query, max_results)
        logger.info("Found %d results", len(results))
        return results