import logging
import random
import re

from services.ollama_service import OllamaService

logger = logging.getLogger(__name__)

_LINKEDIN_PERSONAS = [
    {
        "name": "Alex – Authentic Tech Professional",
        "style": (
            "Write exactly like a human sharing an insightful thought with their professional network. "
            "Start with a conversational hook. Use natural paragraph breaks. "
            "Include 1-2 relevant emojis (like 🤖 for AI, ☁️ for cloud, 🔒 for security) where they feel organic. "
            "End with 2-3 hashtags that are specific and trending in tech (e.g., #AI, #MachineLearning, #TechNews). "
            "Do not sound robotic or use over‑the‑top corporate buzzwords."
        ),
    },
    {
        "name": "Jordan – Curious Engineer",
        "style": (
            "Friendly, low‑key, and analytical. Write like a real developer sharing a quick observation. "
            "Add a single emoji that matches the topic (e.g., 🧠 for ML, ⚡ for performance). "
            "Use 2‑3 hashtags like #TechNews #AI #CloudComputing. Avoid excessive hype."
        ),
    },
]

_FACEBOOK_PERSONAS = [
    {
        "name": "Sam – Tech Enthusiast Friend",
        "style": (
            "Casual, relaxed, everyday tone. Like posting an interesting article link on your personal feed. "
            "Use 2‑3 emojis naturally (😮, 👀, 💡, 🔥). "
            "End with a friendly question and 2 relevant hashtags (e.g., #AI #TechNews). "
            "Keep it under 200 words."
        ),
    },
]

_TWITTER_PERSONAS = [
    {
        "name": "TechTweeter",
        "style": (
            "Short, punchy, and engaging. Like a breaking news alert or a hot take. "
            "Use 1-2 emojis. Include 2-3 relevant hashtags. "
            "Keep it under 250 characters. No fluff, just the key insight. "
            "Sound like a tech enthusiast sharing an exciting update."
        ),
    },
]

_SKIP_PREFIXES = ("here is", "here's", "linkedin post:", "facebook post:", "twitter post:", "tweet:", "post:", "---", "```", "sure", "of course")
_MAX_WORDS_LINKEDIN = 100
_MAX_WORDS_FACEBOOK = 100
_MAX_CHARS_TWITTER = 100


class FormatterAgent:
    def __init__(self, llm_service: OllamaService) -> None:
        self.llm = llm_service

    async def format_for_linkedin(self, summaries: list[str]) -> str:
        if not summaries:
            logger.warning("No summaries provided to FormatterAgent (LinkedIn)")
            return ""

        persona = random.choice(_LINKEDIN_PERSONAS)
        combined = "\n\n".join(f"• {s.strip()}" for s in summaries if s.strip())

        prompt = f"""You are {persona['name']}.
Voice/Style: {persona['style']}

Write ONE natural, human‑sounding LinkedIn post based on the news items below.

HARD RULES:
1. OUTPUT ONLY the post text. No intro, no "Here is the post", no title.
2. Hook: Must sound like a real person making an observation.
3. Flow: Weave the bullet points together into a short, coherent thought.
4. Voice: Authentic, direct, conversational. NO buzzwords.
5. Format: Use line breaks between thoughts.
6. Include 1-2 relevant emojis where they feel natural.
7. End with 2-3 hashtags that are specific to the content (e.g., #GenerativeAI, #CloudNews).
8. Max 180 words.

Tech news:
{combined}

Post:"""

        raw = await self.llm.generate(prompt, temperature=0.7)
        post = self._clean_output(raw, max_words=_MAX_WORDS_LINKEDIN)
        post = self._ensure_hashtags_and_emojis(post, platform="linkedin")
        post = self._post_process(post)
        logger.info("Formatted LinkedIn post (%d words)", len(post.split()))
        return post

    async def format_for_facebook(self, summaries: list[str]) -> str:
        if not summaries:
            logger.warning("No summaries provided to FormatterAgent (Facebook)")
            return ""

        persona = random.choice(_FACEBOOK_PERSONAS)
        combined = "\n\n".join(f"• {s.strip()}" for s in summaries if s.strip())

        prompt = f"""You are {persona['name']}.
Voice/Style: {persona['style']}

Write ONE natural Facebook post based on the news items below.

HARD RULES:
1. OUTPUT ONLY the post text. No intro, no "Here is...", no title.
2. Make it sound like a quick, interesting update shared with friends.
3. Keep it SHORT — maximum 180 words.
4. Plain, everyday language.
5. Include 2‑3 emojis naturally (like 😲, 🤔, 🔥) within the text.
6. End with a simple, friendly question.
7. Add 2 relevant hashtags (e.g., #TechNews #AI).

Tech news:
{combined}

Post:"""

        raw = await self.llm.generate(prompt, temperature=0.7)
        post = self._clean_output(raw, max_words=_MAX_WORDS_FACEBOOK)
        post = self._ensure_hashtags_and_emojis(post, platform="facebook")
        post = self._post_process(post)
        logger.info("Formatted Facebook post (%d words)", len(post.split()))
        return post

    async def format_for_twitter(self, summaries: list[str]) -> str:
        if not summaries:
            logger.warning("No summaries provided to FormatterAgent (Twitter)")
            return ""

        persona = random.choice(_TWITTER_PERSONAS)
        combined = "\n".join(f"- {s.strip()}" for s in summaries if s.strip())

        prompt = f"""You are {persona['name']}.
Voice/Style: {persona['style']}

Write ONE short, engaging tweet based on the news items below.

HARD RULES:
1. OUTPUT ONLY the tweet text. No intro, no "Here is the tweet", no title.
2. Maximum 250 characters (to leave room for a link or retweet).
3. Be exciting and shareable – like a news flash or interesting fact.
4. Use 1-2 emojis, and 2-3 relevant hashtags (e.g., #AI #TechNews).
5. Do NOT use markdown, line breaks, or URLs.

Tech news:
{combined}

Tweet:"""

        raw = await self.llm.generate(prompt, temperature=0.7)
        tweet = self._clean_output(raw, max_words=50)
        tweet = self._ensure_hashtags_and_emojis(tweet, platform="twitter")
        tweet = self._post_process(tweet)
        if len(tweet) > _MAX_CHARS_TWITTER:
            tweet = tweet[:_MAX_CHARS_TWITTER - 3] + "..."
        logger.info("Formatted Twitter post (%d chars)", len(tweet))
        return tweet

    @staticmethod
    def _ensure_hashtags_and_emojis(text: str, platform: str) -> str:
        """Fallback: if no hashtags or emojis, add generic ones."""
        # Check for hashtags
        if not re.search(r'#\w+', text):
            if platform == "linkedin":
                text += "\n\n#TechNews #AI #Innovation"
            elif platform == "facebook":
                text += "\n\n#TechNews #AI"
            else:
                text += " #TechNews #AI"
        # Check for emojis (very basic)
        emoji_pattern = re.compile("["
                                   u"\U0001F600-\U0001F64F"
                                   u"\U0001F300-\U0001F5FF"
                                   u"\U0001F680-\U0001F6FF"
                                   u"\U0001F1E0-\U0001F1FF"
                                   "]+", flags=re.UNICODE)
        if not emoji_pattern.search(text):
            if platform == "linkedin":
                text = "🤖 " + text
            elif platform == "facebook":
                text = "🔥 " + text
            else:
                text = "🚀 " + text
        return text

    @staticmethod
    def _clean_output(text: str, max_words: int = _MAX_WORDS_LINKEDIN) -> str:
        text = text.strip()
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            text = text[1:-1].strip()

        lines = text.splitlines()
        while lines:
            norm = lines[0].lower().strip().lstrip("# ")
            if any(norm.startswith(p) for p in _SKIP_PREFIXES):
                lines.pop(0)
            else:
                break
        while lines and lines[-1].strip() in ("---", "```", ""):
            lines.pop()
        cleaned = "\n".join(lines).strip()
        words = cleaned.split()
        if len(words) > max_words:
            trimmed = " ".join(words[:max_words])
            for p in (".", "!", "?"):
                idx = trimmed.rfind(p)
                if idx > 0:
                    trimmed = trimmed[: idx + 1]
                    break
            cleaned = trimmed
        return cleaned

    @staticmethod
    def _post_process(text: str) -> str:
        text = re.sub(r'([\U00010000-\U0010FFFF])\1+', r'\1', text)
        text = re.sub(r'\s+([,.!?:])', r'\1', text)
        text = re.sub(r'!{2,}', '!', text)
        text = re.sub(r'(?<![a-zA-Z])!(?![a-zA-Z])', '!', text)
        text = re.sub(r'\.(?=[A-Z])', r'. ', text)
        text = re.sub(r' +$', '', text, flags=re.MULTILINE)
        text = re.sub(r'\.\.', '.', text)
        # Ensure space before hashtags
        text = re.sub(r'([^ ])(#)', r'\1 \2', text)
        return text