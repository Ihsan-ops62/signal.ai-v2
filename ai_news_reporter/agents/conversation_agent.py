import asyncio
import logging
import re
import time
from typing import Optional, Dict, Any, AsyncIterator, Callable, List
from collections import OrderedDict

from services.ollama_service import OllamaService
from agents.memory_agent import MemoryAgent
from agents.linkedin_agent import LinkedInAgent
from agents.facebook_agent import FacebookAgent
from agents.twitter_agent import TwitterAgent

logger = logging.getLogger(__name__)

_STATE_AWAITING_CONFIRM = "awaiting_confirm"
_STATE_CANCELLED        = "cancelled"
_STATE_POSTED           = "posted"


class ConversationAgent:
    def __init__(self, llm_service: OllamaService, graph) -> None:
        self.llm   = llm_service
        self.graph = graph
        self._contexts: OrderedDict[str, list] = OrderedDict()
        self._pending_sessions: Dict[str, Dict[str, Any]] = {}
        self._last_graph_state: Dict[str, Dict[str, Any]] = {}
        self._max_contexts = 100

    async def _get_context(self, session_id: str) -> list:
        if session_id not in self._contexts:
            saved = await MemoryAgent.load_context(session_id)
            self._contexts[session_id] = saved or []
            while len(self._contexts) > self._max_contexts:
                self._contexts.popitem(last=False)
        return self._contexts[session_id]

    async def _save_context(self, session_id: str, context: list,
                            user_id: Optional[str] = None) -> None:
        self._contexts[session_id] = context
        await MemoryAgent.save_context(session_id, context, user_id=user_id)

    async def _add_to_context(self, session_id: str, role: str, message: str,
                              user_id: Optional[str] = None) -> None:
        ctx = await self._get_context(session_id)
        ctx.append({"role": role, "message": message})
        if len(ctx) > 20:
            ctx[:] = ctx[-20:]
        await self._save_context(session_id, ctx, user_id=user_id)

    async def chat(self, user_message: str, session_id: Optional[str] = None,
                   voice_mode: bool = False, user_id: Optional[str] = None) -> str:
        response = ""
        async for chunk in self.chat_stream(user_message, session_id, voice_mode, user_id=user_id):
            response += chunk
        return response

    def _extract_post_content(self, user_message: str) -> Optional[str]:
        msg = user_message.strip()

        # 1. Extract from explicit quotes first (always prioritized)
        quote_pattern = r'["\'](.*?)["\']|“([^”]*)”|‘([^’]*)’'
        matches = re.findall(quote_pattern, msg)
        quoted = []
        for m in matches:
            for part in m:
                if part:
                    quoted.append(part)
        if quoted:
            return max(quoted, key=len)
        
        # 2. Extract based on natural conversational intent prefixes
        lower_msg = msg.lower()
        prefixes = [
            "i want to post that", "i want to post", 
            "can you post that", "can you post", 
            "post that", "post this", "post the following",
            "upload that", "upload this", 
            "share that", "share this",
            "tweet that", "tweet this"
        ]

        extracted = None
        for prefix in prefixes:
            idx = lower_msg.find(prefix)
            if idx != -1:
                start_idx = idx + len(prefix)
                # Strip leading colons, dashes, or whitespace
                extracted = msg[start_idx:].lstrip(" :-,")
                break

        # Fallback for simple "post [content]"
        if not extracted and lower_msg.startswith("post "):
            extracted = msg[5:].strip()

        if extracted:
            # Clean up destination tags at the end of the message (e.g., " to linkedin")
            extracted = re.sub(r'(?i)\s+(to|on|in)\s+(linkedin|facebook|twitter|fb|x)[.\s]*$', '', extracted)
            
            # Clean up any lingering edge quotes
            extracted = extracted.strip(' "\'”’“‘')
            
            # Ensure it's substantial enough to be a post
            if len(extracted) > 5:
                return extracted
                
        return None

    def detect_platforms(self, user_message: str) -> List[str]:
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
        """If user wants to post but no news summaries exist, offer to search first."""
        cached = self._last_graph_state.get(session_id)
        if cached and cached.get("summaries"):
            return None  # proceed normally
        msg = ("I don't have any recent news to post. "
               "Would you like me to **search for tech news** first? "
               "Just say something like *'Find AI news'* and then you can post it.")
        await self._add_to_context(session_id, "assistant", msg, user_id=user_id)
        return msg

    async def chat_stream(
        self, user_message: str, session_id: Optional[str] = None,
        voice_mode: bool = False, progress_callback: Optional[Callable] = None,
        user_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        if not session_id:
            session_id = "default"

        direct_content = self._extract_post_content(user_message)
        if direct_content:
            # Detect which platforms the user wants to post to
            platforms = self.detect_platforms(user_message)
            
            if session_id in self._pending_sessions:
                logger.info("Clearing pending session %s due to new direct post", session_id)
                del self._pending_sessions[session_id]
                await MemoryAgent.delete_session(session_id)
            
            results = []
            for platform in platforms:
                try:
                    if platform == "linkedin":
                        result = await LinkedInAgent.post(content=direct_content, username=user_id)
                    elif platform == "facebook":
                        result = await FacebookAgent.post(content=direct_content, username=user_id)
                    elif platform == "twitter":
                        result = await TwitterAgent.post(content=direct_content, username=user_id)
                    else:
                        result = {"success": False, "error": f"Unsupported platform {platform}"}
                    result["platform"] = platform
                    results.append(result)
                except Exception as e:
                    logger.error(f"Direct post to {platform} failed: %s", e)
                    results.append({"success": False, "error": str(e), "platform": platform})
            
            # Build response message
            response = self._build_multi_platform_response(results)
            
            await self._add_to_context(session_id, "user", user_message, user_id=user_id)
            await self._add_to_context(session_id, "assistant", response, user_id=user_id)
            yield response
            return

        if session_id not in self._pending_sessions:
            saved = await MemoryAgent.load_session(session_id)
            if saved:
                self._pending_sessions[session_id] = saved

        pending = self._pending_sessions.get(session_id)

        if pending:
            graph_state = pending["graph_state"]
            status      = pending["status"]

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
                    # Multi-platform direct post (similar to above)
                    platforms = self.detect_platforms(user_message)
                    results = []
                    for platform in platforms:
                        try:
                            if platform == "linkedin":
                                result = await LinkedInAgent.post(content=direct_content, username=user_id)
                            elif platform == "facebook":
                                result = await FacebookAgent.post(content=direct_content, username=user_id)
                            elif platform == "twitter":
                                result = await TwitterAgent.post(content=direct_content, username=user_id)
                            else:
                                result = {"success": False, "error": f"Unsupported platform {platform}"}
                            result["platform"] = platform
                            results.append(result)
                        except Exception as e:
                            logger.error(f"Direct post to {platform} failed: %s", e)
                            results.append({"success": False, "error": str(e), "platform": platform})
                    response = self._build_multi_platform_response(results)
                    await self._add_to_context(session_id, "user", user_message, user_id=user_id)
                    await self._add_to_context(session_id, "assistant", response, user_id=user_id)
                    yield response
                    return
                
                # Guard: check if we have news summaries to post
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

        full_response = ""
        async for token in self._stream_freeform(user_message, session_id, voice_mode):
            full_response += token
            yield token
        await self._add_to_context(session_id, "user", user_message, user_id=user_id)
        await self._add_to_context(session_id, "assistant", full_response, user_id=user_id)

    def _build_multi_platform_response(self, results: List[Dict]) -> str:
        """Construct a user-friendly message from multiple platform post results."""
        successes = []
        failures = []
        for res in results:
            platform = res.get("platform", "unknown")
            if res.get("success"):
                post_id = res.get("post_id") or res.get("tweet_id")
                if post_id and post_id != "unknown":
                    if platform == "linkedin":
                        link = f"https://www.linkedin.com/feed/update/{post_id}"
                    elif platform == "twitter":
                        link = f"https://twitter.com/i/web/status/{post_id}"
                    else:
                        link = ""
                    if link:
                        successes.append(f"{platform.capitalize()}: [View post]({link})")
                    else:
                        successes.append(f"{platform.capitalize()}")
                else:
                    successes.append(f"{platform.capitalize()}")
            else:
                failures.append(f"{platform.capitalize()}: {res.get('error', 'Unknown error')}")
        
        parts = []
        if successes:
            parts.append("✅ **Posted successfully to:**\n" + "\n".join(f"• {s}" for s in successes))
        if failures:
            parts.append("❌ **Failed to post to:**\n" + "\n".join(f"• {f}" for f in failures))
        return "\n\n".join(parts)

    async def _stream_freeform(self, user_message: str, session_id: str,
                                voice_mode: bool) -> AsyncIterator[str]:
        ctx         = await self._get_context(session_id)
        context_str = self._build_context_from_list(ctx)

        if voice_mode:
            prompt = (
                'You are "Signal", a friendly AI assistant speaking naturally.\n'
                f"Conversation context:\n{context_str}\n"
                f'User just said: "{user_message}"\n'
                "Respond in 1-2 spoken sentences. No emojis or hashtags."
            )
        else:
            prompt = (
                'You are "Signal", a warm, highly capable AI assistant. '
                "You help with tech news, social media posts, and discussing software engineering.\n\n"
                f"Current conversation:\n{context_str}\n"
                f'User just said: "{user_message}"\n\n'
                "Respond naturally, intelligently, and helpfully. "
                "You understand multi-agent systems, AI, and backend architectures. "
                "Keep responses concise (1-3 sentences) unless the user asks for a detailed explanation."
            )

        try:
            async for token in self.llm.generate_stream(prompt, temperature=0.7):
                yield token
        except Exception as e:
            logger.error("LLM streaming error: %s", e)
            yield f" [Error: {e}]"

    async def _handle_reasoning(self, user_message: str, session_id: str,
                                 graph_state: dict, voice_mode: bool,
                                 user_id: Optional[str] = None) -> Optional[str]:
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
        pending = self._pending_sessions.get(session_id)
        if not pending:
            return "Sorry, I lost track of that. Could you start over?"

        graph_state = pending["graph_state"]
        msg_lower   = user_message.lower()

        confirmed = any(w in msg_lower for w in
                        ["yes", "okay", "ok", "sure", "go ahead", "post it", "yep", "yeah", "do it", "publish"])
        declined  = any(w in msg_lower for w in
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
        msg_lower = user_message.lower()
        pending   = self._pending_sessions.get(session_id)
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
        try:
            final_state = await self.graph.resume(graph_state, confirmed=True, username=user_id)
            self._pending_sessions.pop(session_id, None)
            await MemoryAgent.delete_session(session_id)
            return self._build_post_result_message(final_state.get("post_result", {}))
        except Exception as exc:
            logger.error("Resume/post failed: %s", exc)
            return f"Something went wrong while posting: {exc}. Want me to try again?"

    def _build_post_result_message(self, post_result: dict) -> str:
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
                msg += f" Posted to {', '.join(s.capitalize() for s in successes)}!\n"
            if failures:
                msg += f" Failed: {', '.join(failures)}"
            return msg.strip()
        success = post_result.get("success", False)
        post_id = post_result.get("post_id") or post_result.get("tweet_id")
        error   = post_result.get("error", "unknown error")
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
                formatted  = state.get("formatted_content", "")
                summaries  = state.get("summaries", [])
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
        return state.get("user_response") or "Done!"

    def detect_action(self, user_message: str) -> Optional[str]:
        msg_lower     = user_message.lower()
        news_keywords = {"news", "latest", "update", "headline", "article", "story", "find"}
        post_keywords = {"post", "share", "publish", "upload", "uplaod", "tweet"}
        search_kws    = {"search", "find", "get", "fetch"}

        has_news   = any(kw in msg_lower for kw in news_keywords)
        has_post   = any(kw in msg_lower for kw in post_keywords)
        has_search = any(kw in msg_lower for kw in search_kws)

        # Direct post detection
        if has_post and not has_news:
            return "post_social"
            
        if has_news and has_post:
            return "news_then_post"
            
        # Standard conversation vs Search detection
        if has_news or has_search:
            # Expanded conversational bypass list
            trivial = {
                "about yourself", "how are you", "what's up", "hello", "hi", 
                "i am a", "i work with", "i build"
            }
            if any(t in msg_lower for t in trivial):
                return None  # Route to freeform chat
                
            if len(user_message.split()) >= 3:
                return "search_news"
                
        return None

    def _build_context_from_list(self, context: list) -> str:
        if not context:
            return "Start of conversation."
        recent = context[-6:]
        return "\n".join(
            f"{'Assistant' if item['role'] == 'assistant' else 'User'}: {item['message']}"
            for item in recent
        )

    def clear_context(self, session_id: Optional[str] = None):
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