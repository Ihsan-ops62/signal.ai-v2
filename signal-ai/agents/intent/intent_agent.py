import logging
from typing import Optional

from services.llm.router import get_llm_router
from core.exceptions import LLMError

logger = logging.getLogger(__name__)


class IntentAgent:
    """Agent for classifying user intent."""
    
    VALID_INTENTS = [
        "search_news",
        "summarize",
        "post",
        "discuss",
        "help"
    ]
    
    def __init__(self):
        self.name = "IntentAgent"
    
    async def classify(self, query: str) -> str:
        """
        Classify user query intent and return intent string.
        """
        try:
            llm = await get_llm_router()
            
            prompt = f"""
Classify the user's intent from the following query. 
Return ONLY one of these keywords: search_news, summarize, post, discuss, help

Query: "{query}"

Intent:
"""
            
            response = await llm.generate(
                prompt=prompt,
                max_tokens=20,
                temperature=0.1
            )
            
            intent = response.text.strip().lower()
            
            if intent not in self.VALID_INTENTS:
                logger.warning(f"Invalid intent: {intent}, defaulting to discuss")
                intent = "discuss"
            
            logger.info(f"Intent classified: {intent} for query: {query[:50]}...")
            return intent
        
        except Exception as e:
            logger.error(f"Intent classification failed: {str(e)}")
            return "discuss"
    
    def detect_platform(self, query: str) -> str:
        """
        Detect which social platform is mentioned in the query.
        Returns "linkedin", "facebook", "twitter", or "both".
        """
        q = query.lower()
        has_linkedin = "linkedin" in q or "linked in" in q
        has_facebook = "facebook" in q or "fb" in q
        has_twitter = "twitter" in q or "tweet" in q
        
        if has_linkedin and (has_facebook or has_twitter):
            return "both"
        if has_linkedin:
            return "linkedin"
        if has_facebook:
            return "facebook"
        if has_twitter:
            return "twitter"
        return "linkedin"  # default
    
    async def batch_classify(self, queries: list[str]) -> list[dict]:
        """Classify multiple queries (kept for compatibility)."""
        results = []
        for query in queries:
            try:
                intent = await self.classify(query)
                results.append({
                    "intent": intent,
                    "confidence": 0.95,
                    "parameters": {"query": query}
                })
            except Exception as e:
                logger.warning(f"Failed to classify query: {query}")
                results.append({
                    "intent": "discuss",
                    "confidence": 0.0,
                    "parameters": {},
                    "error": str(e)
                })
        return results


# Module-level singleton
_intent_agent = None


async def get_intent_agent() -> IntentAgent:
    """Get or create intent agent."""
    global _intent_agent
    if _intent_agent is None:
        _intent_agent = IntentAgent()
    return _intent_agent