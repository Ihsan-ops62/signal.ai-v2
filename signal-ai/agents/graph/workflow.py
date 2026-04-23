import asyncio
import logging
import os
from typing import Optional, TypedDict, Callable, List, Any, Dict

from langgraph.graph import END, StateGraph

from agents.formatter.formatter_agent import FormatterAgent
from agents.intent.intent_agent import IntentAgent
from agents.social.linkedin_agent import LinkedInAgent
from agents.memory.memory_agent import MemoryAgent
from agents.filter.news_filter_agent import NewsFilterAgent
from agents.summarizer.summarizer_agent import SummarizerAgent
from agents.search.web_search_agent import WebSearchAgent
from services.llm.ollama import OllamaService
from agents.social.twitter_agent import TwitterAgent
from agents.social.facebook_agent import FacebookAgent

logger = logging.getLogger(__name__)

# LangSmith tracing
_LANGSMITH_ENABLED = bool(os.getenv("LANGCHAIN_API_KEY"))
if _LANGSMITH_ENABLED:
    try:
        from langsmith import traceable as _traceable
    except ImportError:
        _LANGSMITH_ENABLED = False
        def _traceable(name=None, **kw):
            def _dec(fn):
                return fn
            return _dec
else:
    def _traceable(name=None, **kw):
        def _dec(fn):
            return fn
        return _dec


class AgentState(TypedDict):
    query:                 str
    intent:                str
    search_results:        List[Dict[str, Any]]
    filtered_news:         List[Dict[str, Any]]
    summaries:             List[str]
    formatted_content:     str
    post_result:           Dict[str, Any]
    query_id:              Optional[str]
    error:                 str
    user_response:         str
    awaiting_confirmation: bool
    confirmed:             bool
    news_preview:          List[Dict[str, str]]
    target_platforms:      List[str]
    progress_callback:     Optional[Callable]
    username:              Optional[str]
    linkedin_token:        Optional[str]


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Callable] = {}

    def register(self, name: str, fn: Callable):
        self._tools[name] = fn
        logger.debug("Tool registered: %s", name)

    async def call(self, name: str, **kwargs):
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not registered")
        return await self._tools[name](**kwargs)


class NewsReporterGraph:

    def __init__(self) -> None:
        self.llm_service = OllamaService()
        self.intent_agent = IntentAgent(self.llm_service)
        self.summarizer = SummarizerAgent(self.llm_service)
        self.formatter = FormatterAgent(self.llm_service)

        self.tools = ToolRegistry()
        self.tools.register("search_news", self._tool_search_news)
        self.tools.register("post_to_linkedin", self._tool_post_linkedin)
        self.tools.register("post_to_facebook", self._tool_post_facebook)
        self.tools.register("post_to_twitter", self._tool_post_twitter)

        self.graph = self._build_graph()
        self._resume_graph = self._build_resume_graph()

  
    # Tool implementations
    @_traceable(name="tool:search_news")
    async def _tool_search_news(self, query: str, max_results: int = 5) -> List[Dict]:
        results = await WebSearchAgent.search(query, max_results)
        return NewsFilterAgent.filter_tech_news(results, max_results=max_results)

    @_traceable(name="tool:post_to_linkedin")
    async def _tool_post_linkedin(self, content: str, username: Optional[str] = None,
                                   access_token: Optional[str] = None) -> Dict:
        return await LinkedInAgent.post(content, access_token=access_token, username=username)

    @_traceable(name="tool:post_to_facebook")
    async def _tool_post_facebook(self, content: str, username: Optional[str] = None,
                                   access_token: Optional[str] = None, page_id: Optional[str] = None) -> Dict:
        return await FacebookAgent.post(content, access_token=access_token, page_id=page_id, username=username)

    @_traceable(name="tool:post_to_twitter")
    async def _tool_post_twitter(self, content: str, username: Optional[str] = None,
                                  access_token: Optional[str] = None) -> Dict:
        return await TwitterAgent.post(content, access_token=access_token, username=username)

   
    # Graph construction
    def _build_graph(self):
        wf = StateGraph(AgentState)

        wf.add_node("classify_intent", self.classify_intent)
        wf.add_node("search_news", self.search_news)
        wf.add_node("filter_news", self.filter_news)
        wf.add_node("summarize_news", self.summarize_news)
        wf.add_node("format_post", self.format_post)
        wf.add_node("await_confirmation", self.await_confirmation)
        wf.add_node("check_confirmation", self.check_confirmation)
        wf.add_node("post_to_platforms", self.post_to_platforms)
        wf.add_node("store_results", self.store_results)
        wf.add_node("prepare_response", self.prepare_response)
        wf.add_node("handle_error", self.handle_error)

        wf.set_entry_point("classify_intent")

        wf.add_conditional_edges(
            "classify_intent",
            self._route_from_classify,
            {
                "news_query": "search_news",
                "format_post": "format_post",
                "news_then_post": "search_news",
                "other": "handle_error",
            },
        )

        wf.add_edge("search_news", "filter_news")
        wf.add_edge("filter_news", "summarize_news")

        wf.add_conditional_edges(
            "summarize_news",
            self._route_after_summarize,
            {
                "format_post": "format_post",
                "prepare_response": "prepare_response",
            },
        )

        wf.add_conditional_edges(
            "format_post",
            self._route_after_format,
            {
                "await_confirmation": "await_confirmation",
                "post_to_platforms": "post_to_platforms",
                "prepare_response": "prepare_response",
            },
        )

        wf.add_edge("await_confirmation", END)

        wf.add_conditional_edges(
            "check_confirmation",
            self._route_after_confirmation,
            {
                "post_to_platforms": "post_to_platforms",
                "prepare_response": "prepare_response",
            },
        )

        wf.add_edge("post_to_platforms", "store_results")
        wf.add_edge("store_results", "prepare_response")
        wf.add_edge("prepare_response", END)
        wf.add_edge("handle_error", "prepare_response")

        return wf.compile()

    def _build_resume_graph(self):
        sub = StateGraph(AgentState)
        sub.add_node("check_confirmation", self.check_confirmation)
        sub.add_node("post_to_platforms", self.post_to_platforms)
        sub.add_node("store_results", self.store_results)
        sub.add_node("prepare_response", self.prepare_response)

        sub.set_entry_point("check_confirmation")
        sub.add_conditional_edges(
            "check_confirmation",
            self._route_after_confirmation,
            {"post_to_platforms": "post_to_platforms", "prepare_response": "prepare_response"},
        )
        sub.add_edge("post_to_platforms", "store_results")
        sub.add_edge("store_results", "prepare_response")
        sub.add_edge("prepare_response", END)
        return sub.compile()

   
    # Routing helpers
    def _route_from_classify(self, state: AgentState) -> str:
        if state.get("error"):
            return "other"
        intent = state.get("intent", "other")
        if intent == "post_request":
            return "format_post"
        return intent if intent in ("news_query", "news_then_post") else "other"

    def _route_after_summarize(self, state: AgentState) -> str:
        if state.get("error") and not state.get("summaries"):
            return "prepare_response"
        return "format_post" if state.get("intent") == "news_then_post" else "prepare_response"

    def _route_after_format(self, state: AgentState) -> str:
        if state.get("error") and not state.get("formatted_content"):
            return "prepare_response"
        intent = state.get("intent")
        if intent == "news_then_post":
            return "await_confirmation"
        if intent == "post_request":
            return "post_to_platforms"
        return "prepare_response"

    def _route_after_confirmation(self, state: AgentState) -> str:
        return "post_to_platforms" if state.get("confirmed") else "prepare_response"

    
    # Node implementations
    @_traceable(name="node:classify_intent")
    async def classify_intent(self, state: AgentState) -> AgentState:
        cb = state.get("progress_callback")
        if cb:
            await cb("classify", "🤔 Understanding your request…")
        try:
            intent = await self.intent_agent.classify(state["query"])
            if not state.get("target_platforms"):
                platform = self.intent_agent.detect_platform(state["query"])
                if platform == "both":
                    target_platforms = ["linkedin", "facebook", "twitter"]
                else:
                    target_platforms = [platform]
            else:
                target_platforms = state["target_platforms"]
            return {**state, "intent": intent, "target_platforms": target_platforms, "error": ""}
        except Exception as exc:
            logger.error("classify_intent failed: %s", exc)
            return {**state, "intent": "other", "error": str(exc)}

    @_traceable(name="node:search_news")
    async def search_news(self, state: AgentState) -> AgentState:
        cb = state.get("progress_callback")
        if cb:
            await cb("search", "🔍 Searching for the latest tech news…")
        try:
            results = await self.tools.call("search_news", query=state["query"])
            return {**state, "search_results": results, "error": ""}
        except Exception as exc:
            logger.error("search_news failed: %s", exc)
            return {**state, "search_results": [], "error": str(exc)}

    @_traceable(name="node:filter_news")
    async def filter_news(self, state: AgentState) -> AgentState:
        filtered = NewsFilterAgent.filter_tech_news(state.get("search_results", []))
        return {**state, "filtered_news": filtered}

    @_traceable(name="node:summarize_news")
    async def summarize_news(self, state: AgentState) -> AgentState:
        cb = state.get("progress_callback")
        if cb:
            await cb("summarize", "📝 Summarising articles…")
        articles = state.get("filtered_news", [])
        summaries = []
        preview = []
        for art in articles[:5]:
            summary = await self.summarizer.summarize(art)
            if summary:
                summaries.append(summary)
                preview.append({
                    "title": art.get("title", ""),
                    "source": art.get("source", art.get("url", "")),
                    "url": art.get("url", ""),
                })
            await MemoryAgent.store_news_article(art)
        if not summaries:
            return {
                **state,
                "summaries": [],
                "news_preview": [],
                "error": "No relevant tech news found for this query.",
            }
        return {**state, "summaries": summaries, "news_preview": preview, "error": ""}

    @_traceable(name="node:format_post")
    async def format_post(self, state: AgentState) -> AgentState:
        # ── GUARD: prevent formatting when no summaries exist for posting ──
        summaries = state.get("summaries", [])
        intent = state.get("intent", "")
        if not summaries and intent in ("post_request", "news_then_post"):
            return {
                **state,
                "error": "No news summaries available to format a post. Please search for news first.",
                "formatted_content": "",
            }

        cb = state.get("progress_callback")
        platforms = state.get("target_platforms", ["linkedin"])
        if cb:
            platform_names = ", ".join(p.capitalize() for p in platforms)
            await cb("format", f"✍️ Crafting post for {platform_names}…")
        try:
            platform = platforms[0] if platforms else "linkedin"
            if platform == "facebook":
                post = await self.formatter.format_for_facebook(summaries)
            elif platform == "twitter":
                post = await self.formatter.format_for_twitter(summaries)
            else:
                post = await self.formatter.format_for_linkedin(summaries)
            return {**state, "formatted_content": post, "error": ""}
        except Exception as exc:
            logger.error("format_post failed: %s", exc)
            return {**state, "formatted_content": "", "error": str(exc)}

    async def await_confirmation(self, state: AgentState) -> AgentState:
        return {**state, "awaiting_confirmation": True}

    async def check_confirmation(self, state: AgentState) -> AgentState:
        return state

    @_traceable(name="node:post_to_platforms")
    async def post_to_platforms(self, state: AgentState) -> AgentState:
        cb = state.get("progress_callback")
        platforms = state.get("target_platforms", ["linkedin"])
        content = state.get("formatted_content", "")
        username = state.get("username")
        token = state.get("linkedin_token")

        results = []
        for platform in platforms:
            if cb:
                await cb("post", f"📤 Publishing to {platform.capitalize()}…")
            result = {}
            for attempt in range(1, 3):
                if platform == "linkedin":
                    result = await self.tools.call("post_to_linkedin", content=content,
                                                   username=username, access_token=token)
                elif platform == "facebook":
                    result = await self.tools.call("post_to_facebook", content=content,
                                                   username=username, access_token=token)
                elif platform == "twitter":
                    result = await self.tools.call("post_to_twitter", content=content,
                                                   username=username, access_token=token)
                else:
                    result = {"success": False, "error": f"Unsupported platform {platform}"}
                    break
                if result.get("success"):
                    break
                if attempt < 2:
                    logger.warning("%s post attempt %d failed, retrying…", platform.capitalize(), attempt)
                    await asyncio.sleep(2)
            result["platform"] = platform
            results.append(result)

        final_result = results[0] if len(results) == 1 else results
        return {**state, "post_result": final_result}

    async def store_results(self, state: AgentState) -> AgentState:
        query_id = await MemoryAgent.store_query(
            state.get("query", ""),
            state.get("intent", ""),
            state.get("user_response", ""),
            user_id=state.get("username"),
        )
        post_results = state.get("post_result", [])
        if isinstance(post_results, dict):
            post_results = [post_results]
        for post_res in post_results:
            await MemoryAgent.store_post_result(
                query_id,
                state.get("formatted_content", ""),
                post_res,
                user_id=state.get("username"),
            )
        return {**state, "query_id": query_id}

    async def prepare_response(self, state: AgentState) -> AgentState:
        response = self._build_response(state)
        return {**state, "user_response": response}

    async def handle_error(self, state: AgentState) -> AgentState:
        intent = state.get("intent", "other")
        if intent == "other":
            msg = (
                "I'm your AI News Reporter! \n\n"
                "I can:\n"
                "• **Search tech news** — e.g. *'Latest AI news'*\n"
                "• **Post to LinkedIn, Facebook, Twitter** — e.g. *'Find ML trends and post to LinkedIn and Facebook'*\n\n"
                "What would you like today?"
            )
        else:
            msg = f"Something went wrong: {state.get('error', 'Unknown error')}"
        return {**state, "user_response": msg}

    
    # Response builder
    def _build_response(self, state: AgentState) -> str:
        intent = state.get("intent", "")
        summaries = state.get("summaries", [])
        preview = state.get("news_preview", [])
        post_res = state.get("post_result", {})
        error = state.get("error", "")
        formatted = state.get("formatted_content", "")
        platforms = state.get("target_platforms", ["linkedin"])

        if error and not summaries:
            return f"{error}"

        parts = []

        if summaries:
            parts.append("##  News Found\n")
            for i, (summary, article) in enumerate(zip(summaries, preview or [{}] * len(summaries)), 1):
                title = article.get("title", f"Article {i}")
                source = article.get("source", "")
                url = article.get("url", "")
                source_tag = f" — *{source}*" if source else ""
                link_tag = f" ([link]({url}))" if url else ""
                parts.append(f"**{i}. {title}**{source_tag}{link_tag}")
                parts.append(f"{summary}\n")

        if intent in ("news_then_post", "post_request") and formatted:
            parts.append("\n---\n")
            platform_names = ", ".join(p.capitalize() for p in platforms)
            parts.append(f"##  Post to {platform_names}\n")
            parts.append(formatted)

            if post_res:
                if isinstance(post_res, list):
                    successes = [r.get("platform") for r in post_res if r.get("success")]
                    failures = [f"{r.get('platform')}: {r.get('error')}" for r in post_res if not r.get("success")]
                    if successes:
                        parts.append(f"\n **Published to {', '.join(s.capitalize() for s in successes)}!**")
                    if failures:
                        parts.append(f"\n**Failed:** {', '.join(failures)}")
                else:
                    success = post_res.get("success", False)
                    post_id = post_res.get("post_id") or post_res.get("tweet_id")
                    post_err = post_res.get("error", "")
                    platform = post_res.get("platform", "linkedin")
                    parts.append("\n")
                    if success:
                        if post_id and post_id != "unknown":
                            link = ""
                            if platform == "linkedin":
                                link = f"https://www.linkedin.com/feed/update/{post_id}"
                            elif platform == "twitter":
                                link = f"https://twitter.com/i/web/status/{post_id}"
                            if link:
                                parts.append(f"**Published to {platform.capitalize()}!** [View post]({link})")
                            else:
                                parts.append(f"**Published to {platform.capitalize()}!**")
                        else:
                            parts.append(f"**Published to {platform.capitalize()}!**")
                    else:
                        parts.append(f"**Publishing failed:** {post_err}")

        if not parts:
            return state.get("user_response") or "Done!"

        return "\n".join(parts)

    
    # State initialisation and public entry points
    def _initial_state(self, query: str, username: Optional[str] = None,
                       progress_callback: Optional[Callable] = None) -> AgentState:
        return {
            "query": query,
            "intent": "",
            "search_results": [],
            "filtered_news": [],
            "summaries": [],
            "formatted_content": "",
            "post_result": {},
            "query_id": None,
            "error": "",
            "user_response": "",
            "awaiting_confirmation": False,
            "confirmed": False,
            "news_preview": [],
            "target_platforms": ["linkedin"],
            "progress_callback": progress_callback,
            "username": username,
            "linkedin_token": None,
        }

    @_traceable(name="graph:run_with_confirmation")
    async def run_with_confirmation(
        self,
        query: str,
        username: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        state = self._initial_state(query, username, progress_callback)
        result = await self.graph.ainvoke(state)
        return dict(result)

    async def run_with_custom_state(
        self,
        initial_state: AgentState,
        progress_callback: Optional[Callable] = None,
        username: Optional[str] = None,
    ) -> Dict[str, Any]:
        if progress_callback:
            initial_state["progress_callback"] = progress_callback
        if username:
            initial_state["username"] = username
        result = await self.graph.ainvoke(initial_state)
        return dict(result)

    @_traceable(name="graph:resume")
    async def resume(
        self,
        state: Dict[str, Any],
        confirmed: bool,
        username: Optional[str] = None,
    ) -> Dict[str, Any]:
        resume_state = {**state, "confirmed": confirmed, "awaiting_confirmation": False}
        if username:
            resume_state["username"] = username
        result = await self._resume_graph.ainvoke(resume_state)
        return dict(result)