"""
services/search/search_service.py – News search service.
Preserves original search_service.py logic.
"""
import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any, List, Dict, Optional
import httpx
import feedparser
from core.config import settings

logger = logging.getLogger(__name__)

TECH_DOMAINS = (
    "techcrunch.com,venturebeat.com,arstechnica.com,wired.com,"
    "theregister.com,zdnet.com,techrepublic.com,thenextweb.com,"
    "siliconangle.com,geekwire.com,tech.eu"
)

RSS_FEEDS = [
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://arstechnica.com/feed/",
    "https://venturebeat.com/feed/",
    "https://www.zdnet.com/news/rss.xml",
    "https://feeds.feedburner.com/venturebeat/SZYF",
    "https://www.technologyreview.com/feed/",
    "https://www.theregister.com/headlines.rss",
    "https://www.wired.com/feed/rss",
]

AI_RSS_FEEDS = [
    "https://news.mit.edu/rss/topic/artificial-intelligence2",
    "https://machinelearningmastery.com/blog/feed/",
    "https://openai.com/news/rss.xml",
    "https://news.google.com/rss/search?q=machine+learning&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=artificial+intelligence&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=deep+learning&hl=en-US&gl=US&ceid=US:en",
]

CYBER_RSS_FEEDS = [
    "https://krebsonsecurity.com/feed/",
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.bleepingcomputer.com/feed/",
    "https://www.darkreading.com/rss.xml",
    "https://news.google.com/rss/search?q=cybersecurity&hl=en-US&gl=US&ceid=US:en",
]

CLOUD_RSS_FEEDS = [
    "https://news.google.com/rss/search?q=cloud+computing+aws+azure&hl=en-US&gl=US&ceid=US:en",
    "https://techcrunch.com/category/cloud/feed/",
]

_TOPIC_FEEDS: dict[str, list[str]] = {
    "machine learning": AI_RSS_FEEDS,
    "artificial intelligence": AI_RSS_FEEDS,
    "deep learning": AI_RSS_FEEDS,
    "llm": AI_RSS_FEEDS,
    "gpt": AI_RSS_FEEDS,
    "ml": AI_RSS_FEEDS,
    "ai": AI_RSS_FEEDS,
    "cyber": CYBER_RSS_FEEDS,
    "security": CYBER_RSS_FEEDS,
    "hack": CYBER_RSS_FEEDS,
    "cloud": CLOUD_RSS_FEEDS,
    "aws": CLOUD_RSS_FEEDS,
    "azure": CLOUD_RSS_FEEDS,
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "at",
    "with", "by", "is", "are", "am", "was", "were", "news", "find", "get",
    "me", "latest", "recent", "new", "please", "can", "post", "share",
    "publish", "linkedin", "facebook", "search", "show", "tell", "give",
    "want", "need", "about", "what", "how",
}

_TECH_ABBREVS = {
    "ai", "ml", "dl", "vr", "ar", "ui", "ux", "os", "api", "gpu", "cpu",
    "llm", "gpt", "nlp", "iot", "saas", "devops", "ci", "cd", "aws",
    "gcp",
}


def _extract_keywords(query: str) -> list[str]:
    q = query.lower().strip()
    multi_phrases = [
        "machine learning", "artificial intelligence", "deep learning",
        "large language model", "natural language processing",
        "computer vision", "generative ai", "data breach", "zero-day",
        "open source", "electric vehicle", "cloud computing",
        "virtual reality", "augmented reality", "reinforcement learning",
    ]
    keywords: list[str] = []
    for phrase in multi_phrases:
        if phrase in q:
            keywords.append(phrase)
            q = q.replace(phrase, " ")
    for word in q.split():
        word = word.strip(".,!?;:\"'")
        if not word:
            continue
        if word in _STOPWORDS:
            continue
        if len(word) > 2 or word in _TECH_ABBREVS:
            keywords.append(word)
    seen: set[str] = set()
    result: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            result.append(kw)
    if not result:
        result = ["technology"]
    logger.debug("Extracted keywords from %r → %r", query, result)
    return result


def _article_matches(title: str, body: str, keywords: list[str]) -> bool:
    text = (title + " " + body).lower()
    return any(kw in text for kw in keywords)


def _pick_feeds(keywords: list[str]) -> list[str]:
    feeds: list[str] = []
    for kw in keywords:
        if kw in _TOPIC_FEEDS:
            for f in _TOPIC_FEEDS[kw]:
                if f not in feeds:
                    feeds.append(f)
    for f in RSS_FEEDS[:5]:
        if f not in feeds:
            feeds.append(f)
    return feeds


async def _fetch_one_rss(
    feed_url: str,
    keywords: list[str],
    max_per_feed: int,
) -> list[dict]:
    try:
        async with httpx.AsyncClient(
            timeout=15.0, follow_redirects=True
        ) as client:
            resp = await client.get(
                feed_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; NewsBot/1.0; "
                        "+https://github.com/signal-ai)"
                    )
                },
            )
            if resp.status_code != 200:
                logger.debug("RSS %s returned HTTP %d", feed_url, resp.status_code)
                return []
            raw = resp.text
    except Exception as exc:
        logger.debug("RSS fetch error for %s: %s", feed_url, exc)
        return []

    try:
        feed = feedparser.parse(raw)
    except Exception as exc:
        logger.debug("feedparser error for %s: %s", feed_url, exc)
        return []

    articles: list[dict] = []
    source_name = feed.feed.get("title", feed_url)

    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        link = entry.get("link", "")

        if not title or not summary:
            continue
        if not _article_matches(title, summary, keywords):
            continue

        published_parsed = entry.get("published_parsed")
        if published_parsed:
            try:
                date_iso = datetime.fromtimestamp(
                    time.mktime(published_parsed)
                ).isoformat()
            except Exception:
                date_iso = datetime.now().isoformat()
        else:
            date_iso = datetime.now().isoformat()

        articles.append({
            "title": title,
            "body": summary[:1500],
            "url": link,
            "source": source_name,
            "date": date_iso,
        })

        if len(articles) >= max_per_feed:
            break

    if articles:
        logger.debug("RSS %s → %d matching articles", feed_url, len(articles))
    return articles


class SearchService:

    async def search(self, query: str, category: Optional[str] = None, limit: int = 10) -> list:
        """Alias for search_news with category parameter (ignored for now)."""
        return await self.search_news(query, max_results=limit)

    async def get_trending(self, limit: int = 10) -> list:
        """Get trending news by searching for 'technology'."""
        return await self.search_news("technology", max_results=limit)

    @staticmethod
    async def search_news(query: str, max_results: int = 5) -> list[dict[str, Any]]:
        api_key = settings.NEWS_API_KEY
        if api_key and api_key.strip():
            results = await SearchService._fetch_from_newsapi(query, max_results, api_key)
            if results:
                logger.info("NewsAPI returned %d real articles", len(results))
                return results
            logger.info("NewsAPI returned 0 articles — falling back to RSS")

        results = await SearchService._fetch_from_rss_parallel(query, max_results)
        if results:
            logger.info("RSS returned %d real articles", len(results))
            return results
        logger.info("RSS returned 0 articles — falling back to GNews")

        results = await SearchService._fetch_from_gnews(query, max_results)
        if results:
            logger.info("GNews returned %d real articles", len(results))
            return results
        logger.info("GNews returned 0 articles — falling back to Google News RSS")

        results = await SearchService._fetch_from_google_news_rss(query, max_results)
        if results:
            logger.info("Google News RSS returned %d real articles", len(results))
            return results
        logger.info("Google News RSS returned 0 — using smart mock as last resort")

        logger.warning("All real news sources failed — using smart mock for: %s", query)
        return SearchService._generate_smart_mock_news(query, max_results)

    @staticmethod
    async def _fetch_from_newsapi(query: str, max_results: int, api_key: str) -> list:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "language": "en",
            "pageSize": max_results * 2,
            "apiKey": api_key,
            "sortBy": "publishedAt",
            "domains": TECH_DOMAINS,
            "searchIn": "title,description",
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
            if data.get("status") != "ok":
                logger.error("NewsAPI error: %s", data.get("message"))
                return []
            articles = data.get("articles", [])
            results = []
            for art in articles[:max_results]:
                if "[Removed]" in (art.get("title") or ""):
                    continue
                results.append({
                    "title": art.get("title", "No title"),
                    "body": art.get("description", "") or art.get("content", ""),
                    "url": art.get("url", ""),
                    "source": art.get("source", {}).get("name", "Tech News"),
                    "date": art.get("publishedAt"),
                })
            return results
        except Exception as exc:
            logger.error("NewsAPI request failed: %s", exc)
            return []

    @staticmethod
    async def _fetch_from_rss_parallel(query: str, max_results: int) -> list:
        keywords = _extract_keywords(query)
        feeds = _pick_feeds(keywords)
        logger.info("RSS parallel fetch: keywords=%r feeds=%d", keywords, len(feeds))
        tasks = [
            _fetch_one_rss(feed_url, keywords, max_per_feed=max_results)
            for feed_url in feeds
        ]
        per_feed_results = await asyncio.gather(*tasks, return_exceptions=True)
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        merged: list[dict] = []
        for feed_result in per_feed_results:
            if isinstance(feed_result, Exception):
                continue
            for art in feed_result:
                url = art.get("url", "")
                title = art.get("title", "").lower().strip()
                if url and url in seen_urls:
                    continue
                if title and title in seen_titles:
                    continue
                if url:
                    seen_urls.add(url)
                if title:
                    seen_titles.add(title)
                merged.append(art)
                if len(merged) >= max_results * 3:
                    break
            if len(merged) >= max_results * 3:
                break

        def _date_key(art: dict) -> str:
            return art.get("date") or ""
        merged.sort(key=_date_key, reverse=True)
        return merged[:max_results]

    @staticmethod
    async def _fetch_from_gnews(query: str, max_results: int) -> list:
        gnews_key = os.getenv("GNEWS_API_KEY")
        if not gnews_key:
            logger.warning("GNEWS_API_KEY not set – skipping GNews fallback")
            return []
        url = "https://gnews.io/api/v4/search"
        params = {
            "q": query,
            "lang": "en",
            "max": max_results,
            "sortby": "publishedAt",
            "apikey": gnews_key,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, params=params)
                if response.status_code == 403:
                    logger.warning("GNews: API key invalid or quota exceeded")
                    return []
                if response.status_code != 200:
                    logger.warning("GNews returned HTTP %d", response.status_code)
                    return []
                data = response.json()
            articles = data.get("articles", [])
            results = []
            for art in articles:
                results.append({
                    "title": art.get("title", "No title"),
                    "body": art.get("description", "") or art.get("content", ""),
                    "url": art.get("url", ""),
                    "source": art.get("source", {}).get("name", "Tech News"),
                    "date": art.get("publishedAt"),
                })
            return results[:max_results]
        except Exception as exc:
            logger.error("GNews failed: %s", exc)
            return []

    @staticmethod
    async def _fetch_from_google_news_rss(query: str, max_results: int) -> list:
        keywords = _extract_keywords(query)
        search_q = "+".join(kw.replace(" ", "+") for kw in keywords[:4])
        feed_url = (
            f"https://news.google.com/rss/search"
            f"?q={search_q}&hl=en-US&gl=US&ceid=US:en"
        )
        articles = await _fetch_one_rss(feed_url, keywords, max_per_feed=max_results)
        for art in articles:
            title = art.get("title", "")
            if " - " in title:
                art["title"] = title.rsplit(" - ", 1)[0].strip()
        return articles[:max_results]

    @staticmethod
    def _generate_smart_mock_news(query: str, max_results: int) -> list:
        q = query.lower()
        topics: dict[str, list[tuple[str, str]]] = {
            "machine learning": [
                ("Meta releases open-source ML framework for edge devices",
                 "Meta's new PyTorch-based framework allows running ML models on low-power hardware."),
                ("Google DeepMind achieves new benchmark in protein folding accuracy",
                 "AlphaFold 3 sets new records with 94% accuracy on unseen protein structures."),
                ("Hugging Face launches free fine-tuning service for small language models",
                 "Developers can now fine-tune models up to 7B parameters at no cost."),
            ],
            "artificial intelligence": [
                ("OpenAI launches GPT-5 with improved reasoning and coding capabilities",
                 "The new model outperforms GPT-4 on 85% of benchmark tasks."),
                ("EU AI Act enforcement begins with mandatory risk assessments",
                 "High-risk AI systems must now be registered in the new EU database."),
                ("NVIDIA announces Blackwell B200 GPU available for cloud providers",
                 "B200 delivers 20 petaflops of AI performance at 700W TDP."),
            ],
            "cybersecurity": [
                ("Critical zero-day vulnerability found in Cisco IOS XE",
                 "Attackers can gain full control without authentication. Patch available."),
                ("Ransomware gang leaks 50 GB of hospital patient data",
                 "BlackSuit group demands $10M after breaching Midwest health network."),
                ("Microsoft patches 4 actively exploited Windows flaws",
                 "Includes privilege escalation bug used in ransomware campaigns."),
            ],
            "cloud": [
                ("AWS unveils Graviton4 processors with 40% performance boost",
                 "The new ARM-based chips target AI inference and database workloads."),
                ("Google Cloud announces Gemini-powered Vertex AI upgrades",
                 "New features include automatic model selection and cost optimisation."),
            ],
            "technology": [
                ("Apple announces M4 Pro chip with dedicated AI accelerator",
                 "New Neural Engine delivers 38 TOPS, enabling on-device AI features."),
                ("Broadcom completes VMware integration with new licensing model",
                 "Enterprise customers face significant price changes under new subscription model."),
            ],
        }
        selected: list[tuple[str, str]] = []
        for topic_key, articles in topics.items():
            if topic_key in q:
                selected.extend(articles)
                break
        if not selected:
            selected = topics["technology"]
        results = []
        source = "TechWire"
        for title, body in selected[:max_results]:
            results.append({
                "title": title,
                "body": body,
                "url": f"https://example.com/{title.lower().replace(' ', '-')[:50]}",
                "source": source,
                "date": datetime.now().isoformat(),
            })
        return results


# Singleton getter
_search_service: Optional[SearchService] = None


async def get_search_service() -> SearchService:
    """Get or create search service singleton."""
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service