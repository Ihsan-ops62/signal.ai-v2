import logging
from typing import Optional, List

from services.search.search_service import get_search_service
from core.exceptions import SearchError

logger = logging.getLogger(__name__)


class NewsSearchAgent:
    """Agent for discovering and filtering news articles."""
    
    def __init__(self):
        self.name = "NewsSearchAgent"
        self.min_quality_score = 40.0
    
    @staticmethod
    async def search(
        query: str,
        category: Optional[str] = None,
        limit: int = 10,
        min_quality: Optional[float] = None
    ) -> List[dict]:
        """
        Search for news articles.
        
        Args:
            query: Search query
            category: Optional news category (ignored in current implementation)
            limit: Max articles to return
            min_quality: Minimum quality score (0-100)
            
        Returns:
            List of article dictionaries (empty list if none found or error)
        """
        try:
            search_service = await get_search_service()
            articles = await search_service.search(
                query=query,
                category=category,
                limit=limit
            )
            # Ensure we always return a list
            if articles is None:
                logger.warning("Search service returned None, using empty list")
                return []
            
            # Filter by quality score if specified
            if min_quality is not None:
                articles = [a for a in articles if a.get("quality_score", 0) >= min_quality]
            
            logger.info(f"Found {len(articles)} articles for query: {query}")
            return articles
        
        except Exception as e:
            logger.error(f"News search failed: {str(e)}")
            # Return empty list instead of raising, to avoid breaking workflow
            return []
    
    @staticmethod
    async def get_trending(self, limit: int = 5) -> List[dict]:
        """
        Get trending news articles.
        
        Args:
            limit: Max articles to return
            
        Returns:
            List of trending articles
        """
        try:
            search_service = await get_search_service()
            articles = await search_service.get_trending(limit=limit)
            if articles is None:
                return []
            logger.info(f"Retrieved {len(articles)} trending articles")
            return articles
        except Exception as e:
            logger.error(f"Trending fetch failed: {str(e)}")
            return []
    
    @staticmethod
    async def search_by_source(
        source: str,
        limit: int = 10
    ) -> List[dict]:
        """
        Search articles from specific source.
        
        Args:
            source: News source name
            limit: Max articles
            
        Returns:
            List of articles from source
        """
        try:
            search_service = await get_search_service()
            articles = await search_service.search(
                query=f"source:{source}",
                limit=limit
            )
            return articles if articles is not None else []
        except Exception as e:
            logger.error(f"Source search failed: {str(e)}")
            return []
    
    @staticmethod
    async def filter_duplicates(articles: List[dict]) -> List[dict]:
        """
        Remove duplicate articles from list.
        
        Args:
            articles: List of articles
            
        Returns:
            Deduplicated list
        """
        if not articles:
            return []
        seen_titles = set()
        unique = []
        for article in articles:
            title = article.get("title", "").lower()
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique.append(article)
        logger.info(f"Filtered duplicates: {len(articles)} -> {len(unique)}")
        return unique


# Singleton getter
_search_agent: Optional[NewsSearchAgent] = None


async def get_search_agent() -> NewsSearchAgent:
    """Get or create search agent."""
    global _search_agent
    if _search_agent is None:
        _search_agent = NewsSearchAgent()
    return _search_agent