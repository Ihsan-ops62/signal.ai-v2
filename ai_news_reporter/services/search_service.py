import asyncio
import logging
from typing import Any

import httpx
from config import config

logger = logging.getLogger(__name__)

# Trusted tech news domains (NewsAPI's `domains` parameter)
TECH_DOMAINS = (
    "techcrunch.com,venturebeat.com,arstechnica.com,wired.com,"
    "theregister.com,zdnet.com,techrepublic.com,thenextweb.com,"
    "siliconangle.com,geekwire.com,tech.eu"
)


class SearchService:

    @staticmethod
    async def search_news(query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """
        Fetch real tech news from NewsAPI using domain restriction.
        If NewsAPI fails or is missing, return tech‑focused mock news.
        """
        api_key = getattr(config, "NEWS_API_KEY", None)
        if not api_key or api_key == "":
            logger.warning("NEWS_API_KEY missing – using tech mock news")
            return SearchService._generate_tech_mock_news(query, max_results)

        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "language": "en",
            "pageSize": max_results,
            "apiKey": api_key,
            "sortBy": "publishedAt",
            "domains": TECH_DOMAINS,          # Only tech sources
            "searchIn": "title,description",  # Prioritize titles
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

            if data.get("status") != "ok":
                logger.error(f"NewsAPI error: {data.get('message')}")
                return SearchService._generate_tech_mock_news(query, max_results)

            articles = data.get("articles", [])
            if not articles:
                logger.warning(f"No tech articles for query: {query}")
                return SearchService._generate_tech_mock_news(query, max_results)

            results = []
            for art in articles[:max_results]:
                results.append({
                    "title": art.get("title", "No title"),
                    "body": art.get("description", "") or art.get("content", ""),
                    "url": art.get("url", ""),
                    "source": art.get("source", {}).get("name", "Tech News"),
                    "date": art.get("publishedAt"),
                })
            logger.info(f"NewsAPI returned {len(results)} tech articles for '{query}'")
            return results

        except Exception as e:
            logger.error(f"NewsAPI request failed: {e}")
            return SearchService._generate_tech_mock_news(query, max_results)

    @staticmethod
    def _generate_tech_mock_news(query: str, max_results: int = 3) -> list[dict[str, Any]]:
        """
        Fallback mock news – always tech‑related, no airport or movies.
        """
        q_lower = query.lower()

        # Pick a relevant tech topic based on query keywords
        if "ai" in q_lower or "artificial intelligence" in q_lower:
            topic = "AI"
            headlines = [
                "OpenAI Unveils GPT-5 with 1M Token Context Window",
                "New AI Model Beats Human Experts at Medical Diagnosis",
                "Europe Passes Landmark AI Liability Act",
                "AI Coding Assistants Now Generate Full-Stack Apps",
                "Deep Learning Breakthrough Reduces Energy Use by 70%"
            ]
            bodies = [
                "The new model can process entire novels in one go, opening up long‑form reasoning tasks.",
                "In blind tests, the system achieved 96% accuracy, surpassing board‑certified doctors.",
                "The law holds developers liable for AI‑caused harm, forcing stricter safety standards.",
                "GitHub Copilot X can now build complete React + Node.js apps from a single prompt.",
                "A novel sparse attention mechanism cuts inference costs dramatically."
            ]
        elif "blockchain" in q_lower or "crypto" in q_lower:
            topic = "Blockchain"
            headlines = [
                "Ethereum 3.0 Rollout Increases TPS to 100,000",
                "Central Banks Announce Joint Digital Currency Framework",
                "ZK‑Proofs Go Mainstream for Enterprise Privacy"
            ]
            bodies = ["..."]  # shorten for brevity
        else:
            # Default tech news
            topic = "Technology"
            headlines = [
                "Google Announces Quantum Supremacy 2.0",
                "Apple Unveils AR Glasses with 8K Displays",
                "Microsoft Launches Cloud-Native OS 'Windows 365'"
            ]
            bodies = ["The new system solves problems in seconds that would take supercomputers millennia."]

        # Build articles
        articles = []
        for i in range(min(max_results, len(headlines))):
            articles.append({
                "title": headlines[i],
                "body": bodies[i] if i < len(bodies) else "Details emerging...",
                "url": f"https://techmock.example/news/{i}",
                "source": "Tech Mock Daily",
                "date": "2026-04-08",
            })
        # Pad if needed
        while len(articles) < max_results:
            articles.append(articles[-1].copy())

        logger.info(f"Generated {len(articles)} tech mock articles for query: {query[:50]}")
        return articles