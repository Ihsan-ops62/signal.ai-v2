import logging
from services.ollama_service import OllamaService

logger = logging.getLogger(__name__)

_MIN_SUMMARY_LENGTH = 100   

class SummarizerAgent:
    _summary_cache = {}  # simple in‑memory cache

    def __init__(self, llm_service: OllamaService):
        self.llm = llm_service

    async def summarize(self, article: dict) -> str:
        title = (article.get("title") or "No title").strip()
        content = (article.get("body") or article.get("description") or "").strip()
        url = article.get("url")

        # Check cache
        if url and url in self._summary_cache:
            logger.debug("Using cached summary for %s", url)
            return self._summary_cache[url]

        if not content:
            logger.warning("Article '%s' has no body/description – skipping", title)
            return ""

        # UPDATED: increased content length limit to 4000 chars
        if len(content) > 4000:
            content = content[:4000] + "…"

        # UPDATED: prompt asks for 4-5 detailed sentences
        prompt = f"""You are a professional tech journalist. 
Write a detailed summary of the news article below in 4-5 sentences.
Include key facts, context, and any notable quotes or figures.
Write in plain English. Do NOT start with "This article" or "The article".

Title: {title}
Content: {content}

Summary:"""

        try:
            raw = await self.llm.generate(prompt)
            summary = raw.strip()

            if len(summary) < _MIN_SUMMARY_LENGTH:
                logger.warning("LLM returned suspiciously short summary for '%s': %r", title, summary)
                return ""

            if url:
                self._summary_cache[url] = summary
            return summary

        except Exception as exc:
            logger.error("LLM summarisation failed for article '%s': %s", title, exc)
            return ""