import logging
import random
import re

from services.ollama_service import OllamaService

logger = logging.getLogger(__name__)

# ── LinkedIn reporter personas ────────────────────────────────────────────────
_LINKEDIN_PERSONAS = [
    {
        "name": "Alex – Authentic Tech Professional",
        "style": (
            "Write exactly like a human sharing an insightful thought with their professional network. "
            "Start with a conversational hook (e.g., 'I was just reading about...'). "
            "Use natural paragraph breaks. Synthesize the news into a flowing thought rather than a list. "
            "Do not sound robotic or use over-the-top corporate buzzwords."
        ),
    },
    {
        "name": "Jordan – Curious Engineer",
        "style": (
            "Friendly, low-key, and analytical. Write like a real developer sharing a quick observation about "
            "some cool news they found today. Avoid excessive hype. Use standard punctuation and natural spacing."
        ),
    },
]

# ── Facebook writer personas ──────────────────────────────────────────────────
_FACEBOOK_PERSONAS = [
    {
        "name": "Sam – Tech Enthusiast Friend",
        "style": (
            "Casual, relaxed, and everyday tone. Like posting an interesting article link on your personal feed. "
            "Talk directly to your friends. A couple of emojis are great. No corporate speak."
        ),
    },
]

_SKIP_PREFIXES = ("here is", "here's", "linkedin post:", "facebook post:", "post:", "---", "```", "sure", "of course")
_MAX_WORDS_LINKEDIN = 250
_MAX_WORDS_FACEBOOK = 120


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

Write ONE natural, human-sounding LinkedIn post based on the news items provided in the <news> tags below.

HARD RULES:
1. OUTPUT ONLY the post text. No intro, no "Here is the post", no title.
2. Hook: Must sound like a real person making an observation.
3. Flow: Do not just list the bullet points. Weave them together into a short, coherent thought.
4. Voice: Authentic, direct, conversational. NO buzzwords ("game-changer", "revolutionary", "delve").
5. Format: Use line breaks between thoughts.
6. Punctuation: Keep it normal. Avoid exclamation marks unless truly needed. 
7. End with an engaging, casual question.
8. Add 2-3 hashtags at the very bottom.
9. Max 200 words.

<news>
{combined}
</news>

Post:"""

        raw = await self.llm.generate(prompt, temperature=0.65)
        post = self._clean_output(raw, max_words=_MAX_WORDS_LINKEDIN)
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

Write ONE natural Facebook post based on the news items provided in the <news> tags below.

HARD RULES:
1. OUTPUT ONLY the post text. No intro, no "Here is...", no title.
2. Make it sound like a quick, interesting update shared with friends.
3. Keep it SHORT — maximum 100 words. 
4. Plain, everyday language. 
5. 1-2 emojis max.
6. End with a simple, friendly question.
7. NO hashtags.

<news>
{combined}
</news>

Post:"""

        raw = await self.llm.generate(prompt, temperature=0.7)
        post = self._clean_output(raw, max_words=_MAX_WORDS_FACEBOOK)
        post = self._post_process(post)
        post = re.sub(r'\s*#\w+', '', post).strip()
        logger.info("Formatted Facebook post (%d words)", len(post.split()))
        return post

    @staticmethod
    def _clean_output(text: str, max_words: int = _MAX_WORDS_LINKEDIN) -> str:
        lines = text.strip().splitlines()
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
        text = re.sub(r'!{2,}', '.', text)
        text = re.sub(r'(?<![a-zA-Z])!(?![a-zA-Z])', '.', text)
        text = re.sub(r'\.(?=[A-Z])', r'. ', text)
        text = re.sub(r' +$', '', text, flags=re.MULTILINE)
        text = re.sub(r'\.\.', '.', text)
        return text