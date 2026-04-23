import logging
import re

from services.search.search_service import SearchService, _extract_keywords

logger = logging.getLogger(__name__)

# Short tech abbreviations expanded to full form for better search
_EXPANSIONS: dict[str, str] = {
    r"\bml\b":  "machine learning",
    r"\bai\b":  "artificial intelligence",
    r"\bllm\b": "large language model",
    r"\bnlp\b": "natural language processing",
    r"\biot\b": "internet of things",
    r"\bvr\b":  "virtual reality",
    r"\bar\b":  "augmented reality",
    r"\bcv\b":  "computer vision",
    r"\brl\b":  "reinforcement learning",
}

# Broad topics that don't need "technology news" appended
_TECH_TERMS = {
    "machine learning", "artificial intelligence", "deep learning",
    "cybersecurity", "cloud computing", "blockchain", "kubernetes",
    "docker", "devops", "nvidia", "openai", "google", "microsoft",
    "llm", "gpt", "neural", "semiconductor",
}


class WebSearchAgent:

    @staticmethod
    def _build_search_query(user_query: str) -> str:
        
        #  expand abbreviations
        expanded = user_query.lower()
        for pattern, replacement in _EXPANSIONS.items():
            expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)

        # extract meaningful keywords
        keywords = _extract_keywords(expanded)

        # build query string (prefer multi-word phrases first)
        multi_word   = [k for k in keywords if " " in k]
        single_words = [k for k in keywords if " " not in k]
        ordered      = multi_word + single_words  # multi-word first

        # Take up to 4 terms (phrases count as 1 term each)
        query_parts = ordered[:4]
        search_query = " ".join(query_parts)

        # append news if not already present and no obvious topic coverage
        already_has_tech = any(term in search_query for term in _TECH_TERMS)
        has_news_word    = any(w in search_query for w in ["news", "latest", "update"])

        if not has_news_word and not already_has_tech:
            search_query += " technology news"

        logger.info("Search query: %r → %r", user_query[:60], search_query)
        return search_query

    @staticmethod
    async def search(query: str, max_results: int = 5) -> list:
        """Search for tech news using the cleaned query."""
        search_query = WebSearchAgent._build_search_query(query)
        results = await SearchService.search_news(search_query, max_results)
        logger.info("WebSearchAgent found %d results for %r", len(results), search_query)
        return results