"""
Content summarization agent for Signal AI.
Summarizes articles using LLM with different styles.
"""

import logging
from typing import Optional, List

from services.llm.router import get_llm_router
from core.exceptions import LLMError

logger = logging.getLogger(__name__)


class SummarizerAgent:
    """Agent for summarizing news content."""
    
    SUMMARY_STYLES = {
        "brief": {
            "max_tokens": 100,
            "instruction": "Summarize in 1-2 sentences"
        },
        "detailed": {
            "max_tokens": 300,
            "instruction": "Provide a detailed summary with key points (3-5 sentences)"
        },
        "bullet_points": {
            "max_tokens": 200,
            "instruction": "Summarize as 3-5 key bullet points"
        }
    }
    
    def __init__(self):
        self.name = "SummarizerAgent"
    
    async def summarize(
        self,
        content: str,
        title: Optional[str] = None,
        style: str = "brief"
    ) -> dict:
        """
        Summarize article content.
        
        Args:
            content: Article text to summarize
            title: Optional article title for context
            style: Summary style (brief, detailed, bullet_points)
            
        Returns:
            Dict with summary and metadata
        """
        try:
            if not content or len(content) < 50:
                return {
                    "summary": content,
                    "style": style,
                    "length": len(content),
                    "key_points": []
                }
            
            # Validate style
            if style not in self.SUMMARY_STYLES:
                style = "brief"
            
            config = self.SUMMARY_STYLES[style]
            llm = await get_llm_router()
            
            # Build prompt
            context = f"Article Title: {title}\n" if title else ""
            prompt = f"""
{context}
Article Content:
{content}

{config['instruction']}:
"""
            
            response = await llm.generate(
                prompt=prompt,
                max_tokens=config["max_tokens"],
                temperature=0.5
            )
            
            summary = response.text.strip()
            
            # Extract key points if bullet style
            key_points = []
            if style == "bullet_points":
                key_points = [line.strip() for line in summary.split("\n") if line.strip()]
            
            result = {
                "summary": summary,
                "style": style,
                "length": len(content),
                "summary_length": len(summary),
                "compression_ratio": len(summary) / len(content) if content else 0,
                "key_points": key_points
            }
            
            logger.info(f"Summarized content: {len(content)} chars -> {len(summary)} chars")
            
            return result
        
        except Exception as e:
            logger.error(f"Summarization failed: {str(e)}")
            raise LLMError(f"Summarization failed: {str(e)}")
    
    async def extract_key_points(self, content: str, num_points: int = 5) -> List[str]:
        """
        Extract key points from content.
        
        Args:
            content: Article text
            num_points: Number of points to extract
            
        Returns:
            List of key points
        """
        try:
            llm = await get_llm_router()
            
            prompt = f"""
Extract the {num_points} most important points from this article:

{content}

Return ONLY a numbered list, one point per line (1., 2., 3., etc.):
"""
            
            response = await llm.generate(
                prompt=prompt,
                max_tokens=300,
                temperature=0.3
            )
            
            # Parse response
            points = []
            for line in response.text.strip().split("\n"):
                line = line.strip()
                if line and len(line) > 3:  # Filter empty/short lines
                    # Remove numbering
                    point = line.lstrip("0123456789.).").strip()
                    if point:
                        points.append(point)
            
            return points[:num_points]
        
        except Exception as e:
            logger.error(f"Key point extraction failed: {str(e)}")
            return []
    
    async def compare_articles(self, articles: List[dict]) -> dict:
        """
        Compare multiple articles and find commonalities.
        
        Args:
            articles: List of article dicts with 'title', 'content'
            
        Returns:
            Comparison analysis
        """
        try:
            if len(articles) < 2:
                return {"error": "Need at least 2 articles to compare"}
            
            llm = await get_llm_router()
            
            # Build article summaries
            articles_text = "\n\n---\n\n".join([
                f"Article {i+1}: {a.get('title', '')}\n{a.get('content', a.get('description', ''))[:500]}"
                for i, a in enumerate(articles[:3])  # Max 3 articles
            ])
            
            prompt = f"""
Compare these {len(articles)} news articles and identify:
1. Common themes
2. Different perspectives
3. Key differences

{articles_text}

Provide a concise comparison:
"""
            
            response = await llm.generate(
                prompt=prompt,
                max_tokens=400,
                temperature=0.6
            )
            
            return {
                "comparison": response.text,
                "articles_count": len(articles),
                "analysis_type": "comparison"
            }
        
        except Exception as e:
            logger.error(f"Comparison failed: {str(e)}")
            return {"error": str(e)}
    
    async def summarize_batch(
        self,
        articles: List[dict],
        style: str = "brief"
    ) -> List[dict]:
        """
        Summarize multiple articles.
        
        Args:
            articles: List of article dicts
            style: Summary style
            
        Returns:
            List of articles with summaries
        """
        results = []
        
        for article in articles:
            try:
                content = article.get("content") or article.get("description", "")
                title = article.get("title")
                
                summary_result = await self.summarize(content, title, style)
                
                article["summary"] = summary_result["summary"]
                article["summary_data"] = summary_result
                results.append(article)
                
            except Exception as e:
                logger.warning(f"Failed to summarize article: {article.get('title')}")
                article["summary"] = None
                article["error"] = str(e)
                results.append(article)
        
        return results


# Module-level singleton
_summarizer_agent = None


async def get_summarizer_agent() -> SummarizerAgent:
    """Get or create summarizer agent."""
    global _summarizer_agent
    if _summarizer_agent is None:
        _summarizer_agent = SummarizerAgent()
    return _summarizer_agent
