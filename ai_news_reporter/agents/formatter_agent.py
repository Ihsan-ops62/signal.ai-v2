import logging
import random
import re

from services.ollama_service import OllamaService

logger = logging.getLogger(__name__)

# ── Reporter personas (tuned for cleaner output) ─────────────────────────────
_REPORTER_PERSONAS = [
    {
        "name": "Alex Chen – senior tech reporter",
        "style": (
            "Professional, concise, evidence-driven. Use short paragraphs. "
            "Avoid emojis entirely. No exclamation marks. Sound like a WSJ tech columnist."
        ),
    },
    {
        "name": "Priya Nair – startup beat writer",
        "style": (
            "Conversational but polished. Use at most one emoji per post, and only if it adds clarity. "
            "Avoid over-enthusiasm. Sound like a TechCrunch editor."
        ),
    },
    {
        "name": "Marcus Webb – engineering commentator",
        "style": (
            "Precise, slightly technical, no hype. Zero emojis. No exclamation marks. "
            "Sound like a lead engineer sharing insights on LinkedIn."
        ),
    },
]

_SKIP_PREFIXES = ("here is", "here's", "linkedin post:", "post:", "---", "```", "sure", "of course")
_MAX_WORDS = 250


class FormatterAgent:
    def __init__(self, llm_service: OllamaService) -> None:
        self.llm = llm_service

    async def format_for_linkedin(self, summaries: list[str]) -> str:
        if not summaries:
            logger.warning("No summaries provided to FormatterAgent")
            return ""

        persona = random.choice(_REPORTER_PERSONAS)
        combined = "\n\n".join(f"• {s.strip()}" for s in summaries if s.strip())

        prompt = f"""You are {persona['name']}.
Writing style: {persona['style']}

Write ONE LinkedIn post based on the tech-news bullets below.

HARD RULES:
1. OUTPUT ONLY the post text. No intro, no "Here is…", no title.
2. Hook: first sentence must state the most important fact or trend. Avoid questions as hooks.
3. Body: 3–4 short paragraphs (1–2 sentences each). Blank line between them.
4. Voice: human, direct, no buzzwords ("game-changer", "revolutionary", "disruptive"). Contractions are fine.
5. Emojis: maximum 1 emoji in the entire post. Preferably none.
6. Punctuation: no exclamation marks (except in quoted speech). Use periods and commas normally.
7. Close with ONE specific, open-ended question that professionals would answer.
8. Hashtags: exactly 3 relevant hashtags on the last line, separated by spaces.
9. Max 250 words.

Tech news:
{combined}

Post:"""

        raw = await self.llm.generate(prompt, temperature=0.65)
        post = self._clean_output(raw)
        post = self._post_process(post)
        logger.info("Formatted LinkedIn post (%d words)", len(post.split()))
        return post

    @staticmethod
    def _clean_output(text: str) -> str:
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
        if len(words) > _MAX_WORDS:
            trimmed = " ".join(words[:_MAX_WORDS])
            for p in (".", "!", "?"):
                idx = trimmed.rfind(p)
                if idx > 0:
                    trimmed = trimmed[:idx+1]
                    break
            cleaned = trimmed
        return cleaned

    @staticmethod
    def _post_process(text: str) -> str:
        """Clean up common LLM artifacts."""
        # Remove duplicate consecutive emojis
        text = re.sub(r'([\U00010000-\U0010FFFF])\1+', r'\1', text)
        # Remove spaces before punctuation
        text = re.sub(r'\s+([,.!?:])', r'\1', text)
        # Replace multiple exclamation marks with a single period
        text = re.sub(r'!{2,}', '.', text)
        # Remove exclamation marks entirely (except if part of URL or quoted)
        text = re.sub(r'(?<![a-zA-Z])!(?![a-zA-Z])', '.', text)
        # Ensure single spaces after periods
        text = re.sub(r'\.(?=[A-Z])', r'. ', text)
        # Remove trailing spaces
        text = re.sub(r' +$', '', text, flags=re.MULTILINE)
        # Remove double periods
        text = re.sub(r'\.\.', '.', text)
        return text