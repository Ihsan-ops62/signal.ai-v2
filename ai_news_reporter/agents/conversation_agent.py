import asyncio
import logging
import re
import time
from typing import Optional

from services.ollama_service import OllamaService

logger = logging.getLogger(__name__)

# ── Filler & hedge phrases the LLM tends to insert in voice mode ──────────────
_VOICE_STRIP_RE = re.compile(
    r"^(sure[,!]?|of course[,!]?|absolutely[,!]?|great[,!]?|certainly[,!]?)\s*",
    re.IGNORECASE,
)

# Markdown artefacts that don't read well aloud
_MD_CLEAN_RE = re.compile(r"\*{1,2}([^*]+)\*{1,2}|#{1,6}\s*|`{1,3}")


def _strip_for_voice(text: str) -> str:
    """Remove markdown and filler phrases so TTS reads naturally."""
    text = _MD_CLEAN_RE.sub(r"\1", text)
    text = _VOICE_STRIP_RE.sub("", text)
    # Collapse multiple newlines → single space for TTS
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


class ConversationAgent:
    """
    Natural-language conversation agent that:
    - Understands user intent (voice or text).
    - Answers questions conversationally.
    - Invokes the LangGraph workflow for news/posting actions.
    - Maintains context across turns.
    - Returns voice-clean responses when the caller is in voice mode.
    """

    def __init__(self, llm_service: OllamaService, graph) -> None:
        self.llm = llm_service
        self.graph = graph
        self.context_history: list[dict] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    async def chat(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        voice_mode: bool = False,
    ) -> str:
        if not session_id:
            session_id = "default"

        # ── 1. Pending confirmation? ───────────────────────────────────────────
        # Automatically handled by LangGraph's checkpointer
        if await self.graph.is_awaiting_confirmation(session_id):
            response = await self._handle_confirmation(user_message, session_id)
            return _strip_for_voice(response) if voice_mode else response

        # ── 2. Action needed? ─────────────────────────────────────────────────
        action = self.detect_action(user_message)
        if action in ("search_news", "post_social", "news_then_post"):
            response = await self._execute_action(user_message, action, session_id)
            return _strip_for_voice(response) if voice_mode else response

        # ── 3. Free-form conversation ─────────────────────────────────────────
        response = await self._chat_freeform(user_message, voice_mode=voice_mode)
        return _strip_for_voice(response) if voice_mode else response

    # ── Confirmation handling ──────────────────────────────────────────────────

    async def _handle_confirmation(self, user_message: str, session_id: str) -> str:
        """User replied to a yes/no confirmation prompt."""
        msg_lower = user_message.lower().strip()
        
        # ── 1. Did the user ignore the confirmation and ask a new question? ──
        action = self.detect_action(user_message)
        word_count = len(msg_lower.split())
        
        # If they asked a new question (and it's not just a short "yes, post it")
        if action in ("search_news", "news_then_post", "post_social") and word_count > 3:
            logger.info("User ignored confirmation and asked a new query. Cancelling old state.")
            # Cancel the old paused graph state
            await self.graph.resume(session_id, confirmed=False)
            # Run the new action instead!
            return await self._execute_action(user_message, action, session_id)

        # ── 2. Stricter confirmation check ──
        # Must explicitly start with a confirmation word, or be exactly a confirmation word
        confirm_words = ["yes", "okay", "ok", "sure", "go ahead", "post it", "yep", "yeah", "do it", "publish", "please"]
        
        confirmed = False
        for w in confirm_words:
            if msg_lower == w or msg_lower.startswith(w + " ") or msg_lower.startswith(w + "!") or msg_lower.startswith(w + "."):
                confirmed = True
                break

        # ── 3. Resume the graph ──
        try:
            # Let LangGraph resume from its Checkpointer
            final_state = await self.graph.resume(session_id, confirmed=confirmed)
            
            if not confirmed:
                return "Alright, I've cancelled that post. Is there anything else you want to look up?"

            success  = final_state.get("post_result", {}).get("success", False)
            platform = final_state.get("target_platform", "linkedin").title()
            
            if success:
                return f"Done! I've published the post to {platform}."
                
            error = final_state.get("post_result", {}).get("error", "unknown error")
            return f"I'm sorry, publishing failed. The error was: {error}. Want me to try again?"
            
        except Exception as exc:
            logger.error("Resume failed: %s", exc)
            return f"I ran into a problem while posting: {exc}"

    # ── Graph-backed action ────────────────────────────────────────────────────

    async def _execute_action(
        self, user_message: str, action: str, session_id: str
    ) -> str:
        start = time.monotonic()
        logger.info("Starting graph for: %s", user_message[:50])

        try:
            state = await asyncio.wait_for(
                self.graph.run_with_confirmation(user_message, session_id),
                timeout=600.0,
            )
            logger.info("Graph done in %.2fs", time.monotonic() - start)

            # LangGraph pauses and returns the state object up to the interrupt point
            if state.get("awaiting_confirmation"):
                return state.get(
                    "user_response",
                    "I found something. Should I go ahead and post it?",
                )

            return self._format_graph_response(state)

        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            logger.error("Graph timed out after %.2fs for: %s", elapsed, user_message[:50])
            return (
                "I'm sorry, that search is taking too long. "
                "Please try a simpler query, like 'latest AI news'."
            )
        except Exception as exc:
            logger.error("Graph execution failed: %s", exc)
            return f"Sorry, I couldn't complete that. {exc}"

    def _format_graph_response(self, state: dict) -> str:
        """Produce a friendly, voice-readable summary of graph output."""
        intent     = state.get("intent", "")
        summaries  = state.get("summaries", [])
        post_result = state.get("post_result", {})
        error       = state.get("error", "")

        if error:
            return f"Something went wrong: {error}"
        if intent == "news_query" and summaries:
            count = len(summaries)
            if count == 1:
                return f"Here is what I found: {summaries[0]}"
            intro = f"I found {count} articles. Here is the top story: {summaries[0]}"
            return intro
        if intent in ("post_request", "news_then_post"):
            if post_result.get("success"):
                platform = post_result.get("platform", "social media").title()
                return f"Done! Your post has been published to {platform}."
            return f"Posting failed: {post_result.get('error', 'unknown error')}."
        return state.get("user_response", "Done.")

    # ── Free-form conversation ─────────────────────────────────────────────────

    async def _chat_freeform(
        self, user_message: str, voice_mode: bool = False
    ) -> str:
        """LLM-powered casual conversation."""
        self.context_history.append({"role": "user", "message": user_message})
        context = self._build_context()

        style_note = (
            "You are speaking aloud — use short, natural spoken sentences. "
            "No bullet points, no markdown, no special characters."
            if voice_mode
            else "You may use light markdown."
        )

        prompt = f"""You are "Afan", a highly respectful, warm, and polite AI assistant.
{style_note}

Recent conversation:
{context}

User: "{user_message}"

CRITICAL INSTRUCTIONS:
1. Be exceptionally polite and respectful. If the user is just making a statement (like "ok I will check it", "thank you", or "hello"), reply naturally and politely in 1-2 sentences. Acknowledge them gracefully (e.g., "Take your time," "You are welcome," "Understood").
2. DO NOT lecture the user about your tools or capabilities during normal conversation.
3. ONLY if the user explicitly asks you to find news or post something, but the system didn't catch it, politely guide them: "I would be glad to help with that! Please ask me directly to 'search for news' or 'create a post'."

Reply naturally:"""
        response = (await self.llm.generate(prompt, temperature=0.7)).strip()
        self.context_history.append({"role": "assistant", "message": response})
        # Trim history to last 10 turns
        if len(self.context_history) > 20:
            self.context_history = self.context_history[-20:]
        return response

    # ── Intent & platform detection ───────────────────────────────────────────

    def detect_action(self, user_message: str) -> Optional[str]:
        """Return a coarse action label for routing, or None for free chat."""
        msg = user_message.lower()

        if any(p in msg for p in ["find and post", "search and post", "get news and post"]):
            return "news_then_post"

        # Catch typos like 'uplaod' and broader terms
        if any(kw in msg for kw in ["post", "share", "publish", "upload", "uplaod", "put it on"]):
            if any(p in msg for p in ["linkedin", "facebook", "fb", "social"]):
                return "post_social"
            if any(kw in msg for kw in ["news", "article", "update", "story"]):
                return "news_then_post"
            # Default to post_social if they just say "post it"
            return "post_social" 

        # Expanded keyword list for news searches
        if any(kw in msg for kw in ["news", "latest", "what is", "tell me", "find", "search", "trend", "update", "cyber", "ai", "ml"]):
            return "search_news"

        return None

    def detect_platform(self, user_message: str) -> str:
        msg = user_message.lower()
        if re.search(r"\b(facebook|fb)\b", msg):
            return "facebook"
        return "linkedin"

    # ── Context helpers ────────────────────────────────────────────────────────

    def _build_context(self) -> str:
        if not self.context_history:
            return "Start of conversation."
        recent = self.context_history[-8:]
        lines = []
        for item in recent:
            role = "Afan:" if item["role"] == "assistant" else "User:"
            lines.append(f"{role} {item['message']}")
        return "\n".join(lines)

    def clear_context(self, session_id: Optional[str] = None) -> None:
        self.context_history.clear()
        logger.info("Conversation context cleared")