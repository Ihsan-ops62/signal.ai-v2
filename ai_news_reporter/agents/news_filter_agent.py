import logging
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class NewsFilterAgent:
    # Keyword taxonomy – organised by category for easy extension
    _KEYWORDS: set[str] = {
        # AI / ML
        "ai", "artificial intelligence", "machine learning", "deep learning",
        "neural network", "llm", "large language model", "gpt", "gemini",
        "claude", "mistral", "llama", "diffusion", "transformer", "rag",
        "generative ai", "computer vision", "nlp", "natural language",
        
        # Cloud & infrastructure
        "cloud", "aws", "azure", "gcp", "kubernetes", "docker", "serverless",
        "microservices", "devops", "ci/cd", "infrastructure",
        
        # Cybersecurity
        "cybersecurity", "security", "data breach", "ransomware", "malware",
        "vulnerability", "exploit", "zero-day", "phishing", "encryption",
        
        # Hardware & devices
        "chip", "processor", "gpu", "semiconductor", "nvidia", "amd", "intel",
        "arm", "quantum", "hardware", "robot", "drone", "sensor", "wearable",
        "vr", "ar", "augmented reality", "virtual reality", "headset",
        
        # Software & platforms
        "software", "app", "mobile", "ios", "android", "api", "open source",
        "framework", "platform", "saas", "startup", "tech", "digital",
        "programming", "developer", "code", "github",
        
        # --- NEW: Programming Languages ---
        "python", "javascript", "typescript", "java", "c++", "rust", "golang", 
        "ruby", "php", "sql", "html", "css", "react", "node.js",
        
        # Business / industry trends
        "funding", "ipo", "acquisition", "valuation", "unicorn", "venture",
        "innovation", "disruption", "automation", "blockchain", "crypto",
        "web3", "metaverse", "electric vehicle", "ev", "battery",
    }

    @classmethod
    def filter_tech_news(
        cls,
        articles: List[Dict[str, Any]],
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Return only tech-relevant articles, de-duplicated, up to max_results.
        Title matches are sufficient on their own; body matches require two hits.
        """
        filtered: list[dict] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()

        for art in articles:
            title = art.get("title", "")
            body = art.get("body", art.get("description", ""))
            url = art.get("url", "")

            # De-duplicate
            norm_title = cls._normalise(title)
            if url and url in seen_urls:
                continue
            if norm_title and norm_title in seen_titles:
                continue

            # Keyword matching
            title_lower = title.lower()
            body_lower = body.lower()

            title_hits = sum(1 for kw in cls._KEYWORDS if kw in title_lower)
            body_hits = sum(1 for kw in cls._KEYWORDS if kw in body_lower)

            # Accept if title matches at least once, or body matches twice
            if title_hits >= 1 or body_hits >= 2:
                filtered.append(art)
                if url:
                    seen_urls.add(url)
                if norm_title:
                    seen_titles.add(norm_title)

            if len(filtered) >= max_results:
                break

        logger.info("Tech filter: %d → %d articles", len(articles), len(filtered))
        return filtered

    @staticmethod
    def _normalise(text: str) -> str:
        """Lowercase, strip punctuation, collapse whitespace – for fuzzy dedup."""
        text = text.lower()
        text = re.sub(r"[^\w\s]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text