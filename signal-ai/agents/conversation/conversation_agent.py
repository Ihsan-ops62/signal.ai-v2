
import asyncio
import datetime
import logging
import re
import time
from collections import OrderedDict
from typing import AsyncIterator, Callable, Dict, List, Optional

from services.llm.router import get_llm_router
from infrastructure.database.mongodb import get_mongodb
from core.exceptions import LLMError
from agents.memory.memory_agent import MemoryAgent
from agents.social.linkedin_agent import LinkedInAgent
from agents.social.facebook_agent import FacebookAgent
from agents.social.twitter_agent import TwitterAgent
from agents.graph.workflow import NewsReporterGraph
from agents.graph.state import AgentState

logger = logging.getLogger(__name__)

_STATE_AWAITING_CONFIRM = "awaiting_confirm"
_STATE_CANCELLED = "cancelled"
_STATE_POSTED = "posted"


class ConversationAgent:
    """Agent for managing multi-turn conversations with news and posting capabilities."""

    def __init__(self, graph: NewsReporterGraph):
        self.name = "ConversationAgent"
        self.graph = graph
        self.max_context_messages = 20
        self._contexts: OrderedDict[str, list] = OrderedDict()
        self._pending_sessions: Dict[str, Dict] = {}
        self._last_graph_state: Dict[str, Dict] = {}
        self._max_contexts = 100

    # ---------- Context Management ----------
    async def _get_context(self, session_id: str) -> list:
        if session_id not in self._contexts:
            saved = await MemoryAgent.load_context(session_id)
            self._contexts[session_id] = saved or []
            while len(self._contexts) > self._max_contexts:
                self._contexts.popitem(last=False)
        return self._contexts[session_id]

    async def _save_context(self, session_id: str, context: list, user_id: Optional[str] = None) -> None:
        self._contexts[session_id] = context
        await MemoryAgent.save_context(session_id, context, user_id=user_id)

    async def _add_to_context(self, session_id: str, role: str, message: str, user_id: Optional[str] = None) -> None:
        ctx = await self._get_context(session_id)
        ctx.append({"role": role, "message": message})
        if len(ctx) > self.max_context_messages:
            ctx[:] = ctx[-self.max_context_messages:]
        await self._save_context(session_id, ctx, user_id=user_id)

    # ---------- Public API ----------
    async def chat(self, user_message: str, session_id: Optional[str] = None,
                   voice_mode: bool = False, user_id: Optional[str] = None) -> str:
        response = ""
        async for chunk in self.chat_stream(user_message, session_id, voice_mode, user_id=user_id):
            response += chunk
        return response

    def _extract_post_content(self, user_message: str) -> Optional[str]:
        """Extract explicit post content from user message."""
        msg = user_message.strip()
        quote_pattern = r'["\'](.*?)["\']|“([^”]*)”|‘([^’]*)’'
        matches = re.findall(quote_pattern, msg)
        quoted = [part for m in matches for part in m if part]
        if quoted:
            return max(quoted, key=len)

        typo_variants = r'post|upload|uplaod'
        patterns = [
            rf'(?:{typo_variants})\s+this\s+post\s+(.+?)\s+to\s+linked[ -]?in',
            rf'(?:{typo_variants})\s+this\s+(.+?)\s+to\s+linked[ -]?in',
            rf'(?:{typo_variants})\s+this\s+(.+?)\s+to\s+linkedin',
        ]
        for pat in patterns:
            match = re.search(pat, msg, re.IGNORECASE)
            if match:
                content = match.group(1).strip()
                if content:
                    return content

        simple = re.search(r'^post\s+(.+?)\s+to\s+linked[ -]?in$', msg, re.IGNORECASE)
        if simple:
            return simple.group(1).strip()

        lower_msg = msg.lower()
        if lower_msg.startswith("post ") or lower_msg.startswith("upload ") or lower_msg.startswith("uplaod "):
            if lower_msg.startswith("post "):
                content = msg[5:].strip()
            elif lower_msg.startswith("upload "):
                content = msg[7:].strip()
            else:
                content = msg[7:].strip()
            content = re.sub(r'\s+to\s+linked[ -]?in$', '', content, flags=re.IGNORECASE)
            if content and len(content) < 1000:
                return content
        return None

    def detect_platforms(self, user_message: str) -> List[str]:
        """Detect which social platforms are mentioned."""
        msg = user_message.lower()
        platforms = []
        if "linkedin" in msg or "linked in" in msg:
            platforms.append("linkedin")
        if "facebook" in msg or "fb" in msg:
            platforms.append("facebook")
        if "twitter" in msg or "tweet" in msg:
            platforms.append("twitter")
        if not platforms:
            platforms.append("linkedin")
        return platforms

    async def _handle_post_without_news(self, session_id: str, user_message: str, user_id: Optional[str] = None) -> Optional[str]:
        """Guard against posting without existing news summaries."""
        cached = self._last_graph_state.get(session_id)
        if cached and cached.get("summaries"):
            return None
        msg = ("I don't have any recent news to post. "
               "Would you like me to **search for tech news** first? "
               "Just say something like *'Find AI news'* and then you can post it.")
        await self._add_to_context(session_id, "assistant", msg, user_id=user_id)
        return msg

    async def chat_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        voice_mode: bool = False,
        progress_callback: Optional[Callable] = None,
        user_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream responses for a user message, handling intents and workflows."""
        if not session_id:
            session_id = "default"

        # Direct post with explicit content
        direct_content = self._extract_post_content(user_message)
        if direct_content:
            if session_id in self._pending_sessions:
                logger.info("Clearing pending session %s due to new direct post", session_id)
                del self._pending_sessions[session_id]
                await MemoryAgent.delete_session(session_id)

            try:
                # Try LinkedIn first, can extend to other platforms
                result = await LinkedInAgent.post(content=direct_content, username=user_id)
                if result.get("success"):
                    post_id = result.get("post_id")
                    if post_id and post_id != "unknown":
                        link = f"https://www.linkedin.com/feed/update/{post_id}"
                        response = f" Posted to LinkedIn!\n\n[View post]({link})"
                    else:
                        response = "Posted successfully!"
                else:
                    response = f"Posting failed: {result.get('error', 'Unknown error')}"
            except Exception as e:
                logger.error("Direct post failed: %s", e)
                response = f"Could not post: {e}"

            await self._add_to_context(session_id, "user", user_message, user_id=user_id)
            await self._add_to_context(session_id, "assistant", response, user_id=user_id)
            yield response
            return

        # Restore pending session if exists
        if session_id not in self._pending_sessions:
            saved = await MemoryAgent.load_session(session_id)
            if saved:
                self._pending_sessions[session_id] = saved

        pending = self._pending_sessions.get(session_id)

        if pending:
            graph_state = pending["graph_state"]
            status = pending["status"]

            reasoning_response = await self._handle_reasoning(
                user_message, session_id, graph_state, voice_mode, user_id=user_id
            )
            if reasoning_response is not None:
                await self._add_to_context(session_id, "user", user_message, user_id=user_id)
                await self._add_to_context(session_id, "assistant", reasoning_response, user_id=user_id)
                yield reasoning_response
                return

            if status == _STATE_AWAITING_CONFIRM:
                response = await self._handle_confirmation(user_message, session_id, voice_mode, user_id=user_id)
                await self._add_to_context(session_id, "user", user_message, user_id=user_id)
                await self._add_to_context(session_id, "assistant", response, user_id=user_id)
                yield response
                return

            if status == _STATE_CANCELLED:
                response = await self._handle_post_after_cancel(user_message, session_id, voice_mode, user_id=user_id)
                if response:
                    await self._add_to_context(session_id, "user", user_message, user_id=user_id)
                    await self._add_to_context(session_id, "assistant", response, user_id=user_id)
                    yield response
                    return

        action = self.detect_action(user_message)

        if action in ("search_news", "post_social", "news_then_post"):
            if action == "post_social":
                direct_content = self._extract_post_content(user_message)
                if direct_content:
                    try:
                        result = await LinkedInAgent.post(content=direct_content, username=user_id)
                        if result.get("success"):
                            post_id = result.get("post_id")
                            if post_id and post_id != "unknown":
                                link = f"https://www.linkedin.com/feed/update/{post_id}"
                                response = f"Posted to LinkedIn!\n\n[View post]({link})"
                            else:
                                response = "Posted successfully!"
                        else:
                            response = f"Posting failed: {result.get('error', 'Unknown error')}"
                    except Exception as e:
                        response = f"Could not post: {e}"
                    await self._add_to_context(session_id, "user", user_message, user_id=user_id)
                    await self._add_to_context(session_id, "assistant", response, user_id=user_id)
                    yield response
                    return

                no_news_msg = await self._handle_post_without_news(session_id, user_message, user_id=user_id)
                if no_news_msg:
                    yield no_news_msg
                    return

                cached = self._last_graph_state.get(session_id)
                if cached and cached.get("summaries"):
                    response = await self._execute_action_with_cached_state(
                        user_message, cached, session_id, voice_mode, progress_callback, user_id=user_id
                    )
                    await self._add_to_context(session_id, "user", user_message, user_id=user_id)
                    await self._add_to_context(session_id, "assistant", response, user_id=user_id)
                    yield response
                    return
                else:
                    msg = ("I don't have any recent news summaries to post. "
                           "Would you like me to search for tech news first? "
                           "Or you can provide the exact text you want to post.")
                    yield msg
                    await self._add_to_context(session_id, "user", user_message, user_id=user_id)
                    await self._add_to_context(session_id, "assistant", msg, user_id=user_id)
                    return

            response = await self._execute_action(
                user_message, action, session_id, voice_mode, progress_callback, user_id=user_id
            )
            await self._add_to_context(session_id, "user", user_message, user_id=user_id)
            await self._add_to_context(session_id, "assistant", response, user_id=user_id)
            yield response
            return

        # Freeform chat fallback
        full_response = ""
        async for token in self._stream_freeform(user_message, session_id, voice_mode):
            full_response += token
            yield token
        await self._add_to_context(session_id, "user", user_message, user_id=user_id)
        await self._add_to_context(session_id, "assistant", full_response, user_id=user_id)

    async def _stream_freeform(self, user_message: str, session_id: str, voice_mode: bool) -> AsyncIterator[str]:
        """Handle general conversation not matching specific actions."""
        ctx = await self._get_context(session_id)
        context_str = self._build_context_from_list(ctx)

        if voice_mode:
            prompt = (
                'You are "Alex", a friendly AI assistant speaking naturally.\n'
                f"Conversation context:\n{context_str}\n"
                f'User just said: "{user_message}"\n'
                "Respond in 1-2 spoken sentences. No emojis or hashtags."
            )
        else:
            prompt = (
                'You are "Signal", a warm, human-like AI assistant. '
                "You help with tech news and LinkedIn/Facebook/Twitter posts.\n\n"
                f"Current conversation:\n{context_str}\n"
                f'User just said: "{user_message}"\n\n'
                "Respond naturally, briefly, and helpfully. Use occasional emojis.\n"
                "You can search tech news and post to social media.\n"
                "Keep responses to 1-2 sentences unless more is needed."
            )

        try:
            llm = await get_llm_router()
            async for token in llm.generate_stream(prompt, temperature=0.7):
                yield token
        except Exception as e:
            logger.error("LLM streaming error: %s", e)
            yield f" [Error: {e}]"

    async def _handle_reasoning(self, user_message: str, session_id: str,
                                 graph_state: dict, voice_mode: bool,
                                 user_id: Optional[str] = None) -> Optional[str]:
        """Handle follow-up intents like 'search again' or 'reformat'."""
        msg_lower = user_message.lower()
        search_again_triggers = {
            "search again", "another news", "different news", "try again",
            "find more", "new news", "refresh", "not relevant", "dislike",
        }
        if any(t in msg_lower for t in search_again_triggers):
            original_query = graph_state.get("query", user_message)
            intent = "news_then_post" if "post" in graph_state.get("intent", "") else "search_news"
            return await self._execute_action(f"{original_query} latest", intent, session_id, voice_mode, user_id=user_id)

        reformat_triggers = {
            "reformat", "rewrite", "change format", "improve post",
            "better post", "edit post", "revise post", "redo post",
        }
        if any(t in msg_lower for t in reformat_triggers) and graph_state.get("summaries"):
            platforms = graph_state.get("target_platforms", ["linkedin"])
            platform = platforms[0] if platforms else "linkedin"
            return await self._reformat_and_ask(session_id, graph_state, platform, voice_mode)
        return None

    async def _reformat_and_ask(self, session_id: str, graph_state: dict,
                                  platform: str, voice_mode: bool) -> str:
        """Regenerate formatted post and ask for confirmation."""
        try:
            summaries = graph_state["summaries"]
            if platform == "facebook":
                new_post = await self.graph.formatter.format_for_facebook(summaries)
            elif platform == "twitter":
                new_post = await self.graph.formatter.format_for_twitter(summaries)
                if len(new_post) > 280:
                    new_post = new_post[:277] + "..."
            else:
                new_post = await self.graph.formatter.format_for_linkedin(summaries)
            if not new_post:
                return "Sorry, I couldn't generate a new format. Want me to try a different search?"
            graph_state["formatted_content"] = new_post
            state_copy = {k: v for k, v in graph_state.items() if k != "progress_callback"}
            self._pending_sessions[session_id] = {
                "graph_state": state_copy, "status": _STATE_AWAITING_CONFIRM,
                "created_at": time.monotonic(),
            }
            await MemoryAgent.save_session(session_id, self._pending_sessions[session_id])
            return (
                f"Here's a reformatted {platform.capitalize()} post — does this look better?\n\n{new_post}\n\n"
                "Reply **yes** to publish, **no** to cancel, or **'reformat'** to try again."
            )
        except Exception as exc:
            return f"I couldn't reformat the post: {exc}"

    async def _handle_confirmation(self, user_message: str, session_id: str,
                                    voice_mode: bool, user_id: Optional[str] = None) -> str:
        """Process user confirmation (yes/no) for posting."""
        pending = self._pending_sessions.get(session_id)
        if not pending:
            return "Sorry, I lost track of that. Could you start over?"

        graph_state = pending["graph_state"]
        msg_lower = user_message.lower()

        confirmed = any(w in msg_lower for w in
                        ["yes", "okay", "ok", "sure", "go ahead", "post it", "yep", "yeah", "do it", "publish"])
        declined = any(w in msg_lower for w in
                       ["no", "nope", "cancel", "don't", "stop", "nah", "negative"])

        if confirmed:
            return await self._do_post(session_id, graph_state, voice_mode, user_id=user_id)

        if declined:
            self._pending_sessions[session_id]["status"] = _STATE_CANCELLED
            await MemoryAgent.save_session(session_id, self._pending_sessions[session_id])
            platforms = graph_state.get("target_platforms", ["linkedin"])
            platform_names = ", ".join(p.capitalize() for p in platforms)
            return (
                f"Alright, post to {platform_names} cancelled. "
                "Say 'post it' if you change your mind, or 'search again' for fresher news."
            )

        formatted = graph_state.get("formatted_content", "")
        platforms = graph_state.get("target_platforms", ["linkedin"])
        platform_names = ", ".join(p.capitalize() for p in platforms)
        return (
            f"Just to confirm — shall I publish this post to {platform_names}?\n\n{formatted}\n\n"
            "Say **yes** to publish or **no** to cancel."
        )

    async def _handle_post_after_cancel(self, user_message: str, session_id: str,
                                         voice_mode: bool, user_id: Optional[str] = None) -> Optional[str]:
        """Handle user changing mind after cancelling."""
        msg_lower = user_message.lower()
        pending = self._pending_sessions.get(session_id)
        wants_post = any(w in msg_lower for w in
                         ["post it", "yes", "okay", "ok", "sure", "go ahead", "publish",
                          "want to post", "changed my mind"])
        if wants_post and pending:
            formatted = pending["graph_state"].get("formatted_content", "")
            if formatted:
                self._pending_sessions[session_id]["status"] = _STATE_AWAITING_CONFIRM
                await MemoryAgent.save_session(session_id, self._pending_sessions[session_id])
                platforms = pending["graph_state"].get("target_platforms", ["linkedin"])
                platform_names = ", ".join(p.capitalize() for p in platforms)
                return f"Sure! Here's that post again (to {platform_names}):\n\n{formatted}\n\nSay **yes** to publish it."
            else:
                summaries = pending["graph_state"].get("summaries", [])
                if summaries:
                    platforms = pending["graph_state"].get("target_platforms", ["linkedin"])
                    platform = platforms[0] if platforms else "linkedin"
                    if platform == "facebook":
                        new_post = await self.graph.formatter.format_for_facebook(summaries)
                    elif platform == "twitter":
                        new_post = await self.graph.formatter.format_for_twitter(summaries)
                        if len(new_post) > 280:
                            new_post = new_post[:277] + "..."
                    else:
                        new_post = await self.graph.formatter.format_for_linkedin(summaries)
                    if new_post:
                        pending["graph_state"]["formatted_content"] = new_post
                        self._pending_sessions[session_id]["status"] = _STATE_AWAITING_CONFIRM
                        await MemoryAgent.save_session(session_id, self._pending_sessions[session_id])
                        platform_names = ", ".join(p.capitalize() for p in platforms)
                        return f"Okay, I've re-drafted the post for {platform_names}:\n\n{new_post}\n\nReply **yes** to publish or **no** to cancel."
        return None

    async def _do_post(self, session_id: str, graph_state: dict, voice_mode: bool,
                       user_id: Optional[str] = None) -> str:
        """Execute the actual posting via graph resume."""
        try:
            final_state = await self.graph.resume(graph_state, confirmed=True, username=user_id)
            self._pending_sessions.pop(session_id, None)
            await MemoryAgent.delete_session(session_id)
            return self._build_post_result_message(final_state.get("post_result", {}))
        except Exception as exc:
            logger.error("Resume/post failed: %s", exc)
            return f"Something went wrong while posting: {exc}. Want me to try again?"

    def _build_post_result_message(self, post_result: dict) -> str:
        """Format posting result for user."""
        if not post_result:
            return "Done!"
        if isinstance(post_result, list):
            successes = []
            failures = []
            for res in post_result:
                if res.get("success"):
                    successes.append(res.get("platform", "unknown"))
                else:
                    failures.append(f"{res.get('platform', 'unknown')}: {res.get('error')}")
            msg = ""
            if successes:
                msg += f"Posted to {', '.join(s.capitalize() for s in successes)}!\n"
            if failures:
                msg += f"Failed: {', '.join(failures)}"
            return msg.strip()
        success = post_result.get("success", False)
        post_id = post_result.get("post_id") or post_result.get("tweet_id")
        error = post_result.get("error", "unknown error")
        platform = post_result.get("platform", "linkedin")
        if success:
            if post_id and post_id != "unknown":
                if platform == "linkedin":
                    link = f"https://www.linkedin.com/feed/update/{post_id}"
                elif platform == "twitter":
                    link = f"https://twitter.com/i/web/status/{post_id}"
                else:
                    link = ""
                if link:
                    return f" **Posted to {platform.capitalize()}!**\n\n🔗 [View post]({link})"
            return f" **Posted successfully to {platform.capitalize()}!**"
        return f" **Posting failed:** {error}\n\nWant me to try again?"

    async def _execute_action(self, user_message: str, action: str, session_id: str,
                               voice_mode: bool, progress_callback: Optional[Callable] = None,
                               user_id: Optional[str] = None) -> str:
        """Execute a workflow action (search, post, etc.) using the graph."""
        try:
            platforms = self.detect_platforms(user_message)
            initial_state = self.graph._initial_state(
                query=user_message,
                username=user_id,
                progress_callback=progress_callback
            )
            initial_state["target_platforms"] = platforms

            state = await asyncio.wait_for(
                self.graph.run_with_custom_state(initial_state, progress_callback=progress_callback, username=user_id),
                timeout=600.0,
            )

            if action == "search_news" and state.get("summaries") and not state.get("awaiting_confirmation"):
                self._last_graph_state[session_id] = state

            if state.get("awaiting_confirmation"):
                formatted = state.get("formatted_content", "")
                summaries = state.get("summaries", [])
                state_copy = {k: v for k, v in state.items() if k != "progress_callback"}
                self._pending_sessions[session_id] = {
                    "graph_state": state_copy, "status": _STATE_AWAITING_CONFIRM,
                    "created_at": time.monotonic(),
                }
                await MemoryAgent.save_session(session_id, self._pending_sessions[session_id])

                parts = []
                if summaries:
                    parts.append(f"Here's what I found ({len(summaries)} article(s)):\n")
                    for i, s in enumerate(summaries, 1):
                        parts.append(f"{i}. {s}")
                if formatted:
                    platform_names = ", ".join(p.capitalize() for p in platforms)
                    parts.append(f"\nHere's the post I drafted for {platform_names}:\n")
                    parts.append(formatted)
                parts.append(
                    "\n---\nReply **yes** to publish, **no** to cancel, "
                    "or **'reformat'** to rewrite."
                )
                return "\n".join(parts)

            return self._format_graph_response(state, voice_mode)

        except asyncio.TimeoutError:
            return "That search is taking too long. Try a simpler query like 'latest AI news'."
        except Exception as exc:
            logger.error("Graph execution failed: %s", exc)
            return f"Sorry, I couldn't complete that: {exc}"

    async def _execute_action_with_cached_state(
        self, user_message: str, cached_state: dict, session_id: str,
        voice_mode: bool, progress_callback: Optional[Callable] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Use previously fetched news to format a post without re-searching."""
        summaries = cached_state.get("summaries", [])
        if not summaries:
            return "I don't have any recent news summaries to post. Would you like me to search first?"

        platforms = self.detect_platforms(user_message)
        platform = platforms[0] if platforms else "linkedin"
        try:
            if platform == "facebook":
                formatted = await self.graph.formatter.format_for_facebook(summaries)
            elif platform == "twitter":
                formatted = await self.graph.formatter.format_for_twitter(summaries)
                if len(formatted) > 280:
                    formatted = formatted[:277] + "..."
            else:
                formatted = await self.graph.formatter.format_for_linkedin(summaries)
        except Exception as e:
            return f"Sorry, I couldn't format a post from the cached news: {e}"

        graph_state = {
            "query": user_message,
            "intent": "post_request",
            "target_platforms": platforms,
            "summaries": summaries,
            "news_preview": cached_state.get("news_preview", []),
            "formatted_content": formatted,
            "username": user_id,
        }
        self._pending_sessions[session_id] = {
            "graph_state": graph_state,
            "status": _STATE_AWAITING_CONFIRM,
            "created_at": time.monotonic(),
        }
        await MemoryAgent.save_session(session_id, self._pending_sessions[session_id])

        platform_names = ", ".join(p.capitalize() for p in platforms)
        parts = [
            f"Here's the post I drafted for {platform_names} from the earlier news:\n\n{formatted}\n\n"
            "Say **yes** to publish or **no** to cancel."
        ]
        return "\n".join(parts)

    def _format_graph_response(self, state: dict, voice_mode: bool = False) -> str:
        """Extract user-facing response from graph state."""
        return state.get("user_response") or "Done!"

    def detect_action(self, user_message: str) -> Optional[str]:
        """Determine the user's intent from the message."""
        msg_lower = user_message.lower()
        news_keywords = {"news", "latest", "update", "headline", "article", "story", "find"}
        post_keywords = {"post", "share", "publish", "upload", "uplaod"}
        search_kws = {"search", "find", "get", "fetch"}

        has_news = any(kw in msg_lower for kw in news_keywords)
        has_post = any(kw in msg_lower for kw in post_keywords)
        has_search = any(kw in msg_lower for kw in search_kws)

        if has_news and has_post:
            return "news_then_post"
        if has_post and not has_news:
            return "post_social"
        if has_news or has_search:
            trivial = {"about yourself", "how are you", "what's up", "hello", "hi"}
            if any(t in msg_lower for t in trivial):
                return None
            if len(user_message.split()) >= 3:
                return "search_news"
        return None

    def _build_context_from_list(self, context: list) -> str:
        """Convert context list to string for prompts."""
        if not context:
            return "Start of conversation."
        recent = context[-6:]
        return "\n".join(
            f"{'Assistant' if item['role'] == 'assistant' else 'User'}: {item['message']}"
            for item in recent
        )

    def clear_context(self, session_id: Optional[str] = None):
        """Clear conversation context and pending state."""
        if session_id:
            self._pending_sessions.pop(session_id, None)
            self._last_graph_state.pop(session_id, None)
            self._contexts.pop(session_id, None)
            asyncio.create_task(MemoryAgent.delete_session(session_id))
            asyncio.create_task(MemoryAgent.save_context(session_id, []))
        else:
            self._contexts.clear()
            self._pending_sessions.clear()
            self._last_graph_state.clear()
        logger.info("Conversation context cleared")

    # ---------- New methods for compatibility with old routes (optional) ----------
    async def start_conversation(self, user_id: str, initial_message: Optional[str] = None) -> dict:
        """Legacy method for compatibility."""
        mongodb = await get_mongodb()
        conversation = {
            "user_id": user_id,
            "messages": [],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        if initial_message:
            conversation["messages"].append({"role": "user", "content": initial_message})
        result = await mongodb.insert_one("conversations", conversation)
        conversation["_id"] = str(result.inserted_id)
        return conversation

    async def add_message(self, conversation_id: str, role: str, content: str) -> dict:
        mongodb = await get_mongodb()
        message = {"role": role, "content": content, "timestamp": datetime.utcnow().isoformat()}
        await mongodb.update_one(
            "conversations",
            {"_id": conversation_id},
            {"$push": {"messages": message}, "$set": {"updated_at": datetime.utcnow()}}
        )
        return message

    async def get_conversation(self, conversation_id: str) -> dict:
        mongodb = await get_mongodb()
        conv = await mongodb.find_one("conversations", {"_id": conversation_id})
        if not conv:
            raise ValueError(f"Conversation not found: {conversation_id}")
        return conv

    async def get_context(self, conversation_id: str, num_messages: int = None) -> List[dict]:
        conv = await self.get_conversation(conversation_id)
        messages = conv.get("messages", [])
        limit = num_messages or self.max_context_messages
        return [{"role": m["role"], "content": m["content"]} for m in messages[-limit:]]

    async def generate_response(self, conversation_id: str, user_message: str, system_prompt: Optional[str] = None) -> str:
        context = await self.get_context(conversation_id)
        messages = [{"role": "system", "content": system_prompt or "You are a helpful AI news assistant."}] + context
        messages.append({"role": "user", "content": user_message})
        llm = await get_llm_router()
        response = await llm.chat(messages, max_tokens=500, temperature=0.7)
        await self.add_message(conversation_id, "user", user_message)
        await self.add_message(conversation_id, "assistant", response.text)
        return response.text

    async def summarize_conversation(self, conversation_id: str) -> str:
        conv = await self.get_conversation(conversation_id)
        messages = conv.get("messages", [])
        if len(messages) < 2:
            return "Conversation just started"
        conv_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages[-10:]])
        llm = await get_llm_router()
        prompt = f"Summarize this conversation in 2-3 sentences:\n\n{conv_text}\n\nSummary:"
        response = await llm.generate(prompt=prompt, max_tokens=150, temperature=0.5)
        mongodb = await get_mongodb()
        await mongodb.update_one("conversations", {"_id": conversation_id}, {"$set": {"metadata.summary": response.text}})
        return response.text

    async def extract_topic(self, conversation_id: str) -> str:
        conv = await self.get_conversation(conversation_id)
        first_msg = conv.get("messages", [{}])[0].get("content", "")
        if not first_msg:
            return "general"
        llm = await get_llm_router()
        prompt = f'What is the main topic of this message (max 3 words):\n\n"{first_msg}"\n\nTopic:'
        response = await llm.generate(prompt=prompt, max_tokens=20, temperature=0.3)
        topic = response.text.strip().lower()
        mongodb = await get_mongodb()
        await mongodb.update_one("conversations", {"_id": conversation_id}, {"$set": {"metadata.topic": topic}})
        return topic

    async def get_user_conversations(self, user_id: str, limit: int = 10) -> List[dict]:
        mongodb = await get_mongodb()
        return await mongodb.find_many("conversations", {"user_id": user_id}, limit=limit)


# Module-level singleton
_conversation_agent: Optional[ConversationAgent] = None


async def get_conversation_agent() -> ConversationAgent:
    """Get or create conversation agent (requires graph initialization)."""
    global _conversation_agent
    if _conversation_agent is None:
        from graph.workflow import NewsReporterGraph
        graph = NewsReporterGraph()
        _conversation_agent = ConversationAgent(graph)
    return _conversation_agent