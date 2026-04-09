import asyncio
import logging
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from agents.facebook_agent import FacebookAgent
from agents.formatter_agent import FormatterAgent
from agents.intent_agent import IntentAgent
from agents.linkedin_agent import LinkedInAgent
from agents.memory_agent import MemoryAgent
from agents.news_filter_agent import NewsFilterAgent
from agents.summarizer_agent import SummarizerAgent
from agents.web_search_agent import WebSearchAgent
from services.ollama_service import OllamaService

logger = logging.getLogger(__name__)

# ── State schema ───────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    query:                 str
    intent:                str
    search_results:        list
    filtered_news:         list
    summaries:             list[str]
    formatted_content:     str
    post_result:           dict
    query_id:              Optional[str]   
    error:                 str
    user_response:         str
    awaiting_confirmation: bool            
    confirmed:             bool            
    news_preview:          list[dict]      
    target_platform:       str             


# ── Graph ──────────────────────────────────────────────────────────────────────

class NewsReporterGraph:

    def __init__(self) -> None:
        self.llm_service  = OllamaService()
        self.intent_agent = IntentAgent(self.llm_service)
        self.summarizer   = SummarizerAgent(self.llm_service)
        self.formatter    = FormatterAgent(self.llm_service)
        
        # Built-in checkpointer for state persistence
        self.checkpointer = MemorySaver()
        self.graph        = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(AgentState)

        workflow.add_node("classify_intent",     self.classify_intent)
        workflow.add_node("search_news",         self.search_news)
        workflow.add_node("filter_news",         self.filter_news)
        workflow.add_node("summarize_news",      self.summarize_news)
        workflow.add_node("format_for_linkedin", self.format_for_linkedin)
        workflow.add_node("format_for_facebook", self.format_for_facebook)
        workflow.add_node("await_confirmation",  self.await_confirmation)
        workflow.add_node("check_confirmation",  self.check_confirmation)
        workflow.add_node("post_to_linkedin",    self.post_to_linkedin)
        workflow.add_node("post_to_facebook",    self.post_to_facebook)
        workflow.add_node("store_results",       self.store_results)
        workflow.add_node("prepare_response",    self.prepare_response)
        workflow.add_node("handle_error",        self.handle_error)

        workflow.set_entry_point("classify_intent")

        workflow.add_conditional_edges(
            "classify_intent",
            self._route_from_classify,
            {
                "news_query":          "search_news",
                "format_for_linkedin": "format_for_linkedin",
                "format_for_facebook": "format_for_facebook",
                "news_then_post":      "search_news",
                "other":               "handle_error",
            },
        )

        workflow.add_edge("search_news",  "filter_news")
        workflow.add_edge("filter_news",  "summarize_news")

        workflow.add_conditional_edges(
            "summarize_news",
            self._route_after_summarize,
            {
                "format_for_linkedin": "format_for_linkedin",
                "format_for_facebook": "format_for_facebook",
                "prepare_response":    "prepare_response",
            },
        )

        workflow.add_conditional_edges(
            "format_for_linkedin",
            self._route_after_format,
            {
                "await_confirmation": "await_confirmation",
                "post_to_linkedin":   "post_to_linkedin",
                "prepare_response":   "prepare_response",
            },
        )

        workflow.add_conditional_edges(
            "format_for_facebook",
            self._route_after_format,
            {
                "await_confirmation": "await_confirmation",
                "post_to_facebook":   "post_to_facebook",
                "prepare_response":   "prepare_response",
            },
        )

        workflow.add_edge("await_confirmation", "check_confirmation")

        workflow.add_conditional_edges(
            "check_confirmation",
            self._route_after_confirmation,
            {
                "post_to_linkedin": "post_to_linkedin",
                "post_to_facebook": "post_to_facebook",
                "prepare_response": "prepare_response",
            },
        )

        workflow.add_edge("post_to_linkedin", "store_results")
        workflow.add_edge("post_to_facebook", "store_results")
        workflow.add_edge("store_results",    "prepare_response")
        workflow.add_edge("prepare_response", END)
        workflow.add_edge("handle_error",     "prepare_response")

        # The graph will now automatically pause BEFORE executing 'check_confirmation'
        return workflow.compile(
            checkpointer=self.checkpointer,
            interrupt_before=["check_confirmation"]
        )

    # ── Routing helpers ────────────────────────────────────────────────────────

    def _route_from_classify(self, state: AgentState) -> str:
        if state.get("error"):
            return "other"
        intent   = state.get("intent", "other")
        platform = state.get("target_platform", "linkedin")

        if intent == "post_request":
            return "format_for_facebook" if platform == "facebook" else "format_for_linkedin"
        return intent

    def _route_after_summarize(self, state: AgentState) -> str:
        if state.get("intent") == "news_then_post":
            platform = state.get("target_platform", "linkedin")
            return "format_for_facebook" if platform == "facebook" else "format_for_linkedin"
        return "prepare_response"

    def _route_after_format(self, state: AgentState) -> str:
        if state.get("error"):
            return "prepare_response"
        intent = state.get("intent")
        platform = state.get("target_platform", "linkedin")
        
        if intent == "news_then_post":
            return "await_confirmation"
        elif intent == "post_request":
            return "post_to_facebook" if platform == "facebook" else "post_to_linkedin"
        return "prepare_response"

    def _route_after_confirmation(self, state: AgentState) -> str:
        if not state.get("confirmed"):
            return "prepare_response"
        platform = state.get("target_platform", "linkedin")
        return "post_to_facebook" if platform == "facebook" else "post_to_linkedin"

    # ── Node implementations ───────────────────────────────────────────────────

    async def classify_intent(self, state: AgentState) -> AgentState:
        try:
            state["intent"]          = await self.intent_agent.classify(state["query"])
            state["target_platform"] = self.intent_agent.detect_platform(state["query"])
        except Exception as exc:
            logger.error("classify_intent failed: %s", exc)
            state["error"]           = str(exc)
            state["intent"]          = "other"
            state["target_platform"] = "linkedin"
        return state

    async def search_news(self, state: AgentState) -> AgentState:
        try:
            results = await WebSearchAgent.search(state["query"])
            if not results:
                state["error"] = "No search results returned. Try a different query."
            state["search_results"] = results or []
        except Exception as exc:
            logger.error("search_news failed: %s", exc)
            state["error"]          = f"Search failed: {exc}"
            state["search_results"] = []
        return state

    async def filter_news(self, state: AgentState) -> AgentState:
        try:
            filtered = NewsFilterAgent.filter_tech_news(state.get("search_results", []))
            if not filtered:
                logger.warning("No tech articles after filtering – keeping all results")
                filtered = state.get("search_results", [])
            state["filtered_news"] = filtered
        except Exception as exc:
            logger.error("filter_news failed: %s", exc)
            state["error"]         = f"Filtering failed: {exc}"
            state["filtered_news"] = state.get("search_results", [])
        return state

    async def summarize_news(self, state: AgentState) -> AgentState:
        # Change [:3] to [:2] to cut the processing time by 33%
        articles = state.get("filtered_news", [])[:2] 
        
        sem = asyncio.Semaphore(1)

        async def _process_article(article):
            async with sem:
                try:
                    summary = await self.summarizer.summarize(article)
                    if summary:
                        await MemoryAgent.store_news_article(article)
                    return summary
                except Exception as exc:
                    logger.warning(
                        "Could not summarise article %r: %s",
                        article.get("title", "?"),
                        exc,
                    )
                    return None

        results = await asyncio.gather(*[_process_article(art) for art in articles])
        summaries = [res for res in results if res]

        if not summaries:
            state["error"] = "Could not summarise any articles."

        state["summaries"]    = summaries
        state["news_preview"] = articles
        return state

    async def format_for_linkedin(self, state: AgentState) -> AgentState:
        try:
            summaries = state.get("summaries") or [state["query"]]
            formatted = await self.formatter.format_for_linkedin(summaries)
            if not formatted:
                raise ValueError("Formatter returned empty content")
            state["formatted_content"] = formatted
        except Exception as exc:
            logger.error("format_for_linkedin failed: %s", exc)
            state["error"]             = f"Formatting failed: {exc}"
            state["formatted_content"] = state["query"]
        return state

    async def format_for_facebook(self, state: AgentState) -> AgentState:
        try:
            summaries = state.get("summaries") or [state["query"]]
            formatted = await self.formatter.format_for_facebook(summaries)
            if not formatted:
                raise ValueError("Formatter returned empty content")
            state["formatted_content"] = formatted
        except Exception as exc:
            logger.error("format_for_facebook failed: %s", exc)
            state["error"]             = f"Formatting failed: {exc}"
            state["formatted_content"] = state["query"]
        return state

    async def await_confirmation(self, state: AgentState) -> AgentState:
        formatted = state.get("formatted_content", "")
        platform  = state.get("target_platform", "linkedin").title()

        if not formatted:
            state["awaiting_confirmation"] = False
            state["confirmed"]             = False
            state["error"]                 = "No content to post."
            return state

        state["user_response"] = (
            f"🔍 **I drafted this {platform} post based on the latest news. Shall I publish it?**\n\n"
            f"{formatted}\n\n"
            "---\n"
            "Reply **yes** to post, or **no** to cancel."
        )
        state["awaiting_confirmation"] = True
        state["confirmed"]             = False

        logger.info("Pausing for user confirmation before %s post", platform)
        return state

    async def check_confirmation(self, state: AgentState) -> AgentState:
        # This node runs AFTER the graph is resumed
        logger.info("User confirmation received: %s", state.get("confirmed"))
        return state

    async def post_to_linkedin(self, state: AgentState) -> AgentState:
        try:
            result = await LinkedInAgent.post(state["formatted_content"])
            result["platform"] = "linkedin"
            state["post_result"] = result
        except Exception as exc:
            logger.error("post_to_linkedin failed: %s", exc)
            state["post_result"] = {"success": False, "error": str(exc), "platform": "linkedin"}
        return state

    async def post_to_facebook(self, state: AgentState) -> AgentState:
        try:
            result = await FacebookAgent.post(state["formatted_content"])
            result["platform"] = "facebook"
            state["post_result"] = result
        except Exception as exc:
            logger.error("post_to_facebook failed: %s", exc)
            state["post_result"] = {"success": False, "error": str(exc), "platform": "facebook"}
        return state

    async def store_results(self, state: AgentState) -> AgentState:
        try:
            await MemoryAgent.store_post_result(
                state.get("query_id"),
                state.get("formatted_content", ""),
                state.get("post_result", {}),
            )
        except Exception as exc:
            logger.error("store_results failed (non-fatal): %s", exc)
        return state

    async def prepare_response(self, state: AgentState) -> AgentState:
        intent         = state.get("intent", "other")
        error          = state.get("error", "")
        summaries      = state.get("summaries", [])
        post_result    = state.get("post_result", {})
        platform       = state.get("target_platform", "linkedin").title()
        summaries_text = "\n\n".join(summaries) if summaries else "No summaries available."
        post_success   = post_result.get("success", False)
        post_error     = post_result.get("error", "Unknown error")

        if intent == "news_then_post" and not state.get("confirmed") and summaries:
            state["user_response"] = "Got it — post cancelled."
        elif error and not summaries and not post_success:
            state["user_response"] = f"Error: {error}"
        elif intent == "news_query":
            state["user_response"] = (
                summaries_text if summaries
                else "No relevant tech news found. Please try a more specific query."
            )
        elif intent == "post_request":
            state["user_response"] = (
                f"Successfully posted to {platform}!"
                if post_success
                else f"Failed to post: {post_error}"
            )
        elif intent == "news_then_post":
            if post_success:
                state["user_response"] = f"Posted successfully to {platform}."
            else:
                state["user_response"] = f"News fetched but posting to {platform} failed: {post_error}"
        else:
            state["user_response"] = (
                "I can only help with tech news queries or social media posts (LinkedIn/Facebook). "
                "Try: 'What's the latest in AI?' or 'Find AI news and post it on Facebook'."
            )

        try:
            query_id = await MemoryAgent.store_query(
                state.get("query", ""), intent, state.get("user_response", "")
            )
            state["query_id"] = query_id
        except Exception as exc:
            logger.error("Failed to store query (non-fatal): %s", exc)

        return state

    async def handle_error(self, state: AgentState) -> AgentState:
        if not state.get("error"):
            state["error"] = "Unrecognised request. Please ask about tech news or request a post."
        return state

    # ── Public API ─────────────────────────────────────────────────────────────

    async def is_awaiting_confirmation(self, session_id: str) -> bool:
        """Helper to check if a thread is paused for Human-In-The-Loop."""
        config = {"configurable": {"thread_id": session_id}}
        try:
            state = await self.graph.aget_state(config)
            return bool(state.next and "check_confirmation" in state.next)
        except Exception:
            return False

    async def run(self, query: str) -> str:
        query = (query or "").strip()
        if not query:
            return "Please provide a query."
        state = self._initial_state(query)
        config = {"configurable": {"thread_id": "default_run"}}
        try:
            final = await self.graph.ainvoke(state, config=config)
            return final.get("user_response", "")
        except Exception as exc:
            logger.critical("Graph execution failed: %s", exc, exc_info=True)
            return f"Unexpected error: {exc}"

    async def run_with_confirmation(self, query: str, session_id: str) -> AgentState:
        query = (query or "").strip()
        if not query:
            return {"user_response": "Please provide a query.", "awaiting_confirmation": False}
        
        state = self._initial_state(query)
        config = {"configurable": {"thread_id": session_id}}
        try:
            # Replaces the state inside the thread so fresh queries don't append to old queries
            return await self.graph.ainvoke(state, config=config)
        except Exception as exc:
            logger.critical("Graph execution failed: %s", exc, exc_info=True)
            return {"user_response": f"Unexpected error: {exc}", "awaiting_confirmation": False}

    async def resume(self, session_id: str, confirmed: bool) -> AgentState:
        config = {"configurable": {"thread_id": session_id}}
        
        # Inject the user's decision into the state
        await self.graph.aupdate_state(
            config, 
            {"confirmed": confirmed, "awaiting_confirmation": False}
        )
        
        try:
            # Resume graph execution from the paused point
            return await self.graph.ainvoke(None, config=config)
        except Exception as exc:
            logger.critical("Resume failed: %s", exc, exc_info=True)
            return {"user_response": f"Unexpected error during resume: {exc}"}

    @staticmethod
    def _initial_state(query: str) -> AgentState:
        return AgentState(
            query=query,
            intent="",
            search_results=[],
            filtered_news=[],
            summaries=[],
            formatted_content="",
            post_result={},
            query_id=None,
            error="",
            user_response="",
            awaiting_confirmation=False,
            confirmed=False,
            news_preview=[],
            target_platform="linkedin",
        )