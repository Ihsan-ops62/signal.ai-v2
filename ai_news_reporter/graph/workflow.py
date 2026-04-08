import logging
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

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


# ── State schema ──────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    query:              str
    intent:             str
    search_results:     list
    filtered_news:      list
    summaries:          list[str]
    formatted_content:  str
    post_result:        dict
    query_id:           Optional[str]   # MongoDB ID of the stored user query
    error:              str
    user_response:      str
    # ── NEW fields ────────────────────────────────────────────────────────────
    awaiting_confirmation: bool         # True = paused, waiting for user OK
    confirmed:             bool         # True = user said yes, False = declined
    news_preview:          list[dict]   # trimmed article list shown in confirmation
    target_platform:       str          # 'linkedin' or 'facebook'


# ── Graph ─────────────────────────────────────────────────────────────────────

class NewsReporterGraph:
  
    def __init__(self) -> None:
        self.llm_service  = OllamaService()
        self.intent_agent = IntentAgent(self.llm_service)
        self.summarizer   = SummarizerAgent(self.llm_service)
        self.formatter    = FormatterAgent(self.llm_service)
        self.graph        = self._build_graph()
        self._resume_graph = self._build_resume_graph()  # pre‑compiled for efficiency

    # ── Graph construction ────────────────────────────────────────────────────

    def _build_graph(self):
        workflow = StateGraph(AgentState)

        workflow.add_node("classify_intent",       self.classify_intent)
        workflow.add_node("search_news",           self.search_news)
        workflow.add_node("filter_news",           self.filter_news)
        workflow.add_node("summarize_news",        self.summarize_news)
        workflow.add_node("await_confirmation",    self.await_confirmation)
        workflow.add_node("check_confirmation",    self.check_confirmation)
        workflow.add_node("format_for_linkedin",   self.format_for_linkedin)
        workflow.add_node("format_for_facebook",   self.format_for_facebook)
        workflow.add_node("post_to_linkedin",      self.post_to_linkedin)
        workflow.add_node("post_to_facebook",      self.post_to_facebook)
        workflow.add_node("store_results",         self.store_results)
        workflow.add_node("prepare_response",      self.prepare_response)
        workflow.add_node("handle_error",          self.handle_error)

        workflow.set_entry_point("classify_intent")

        workflow.add_conditional_edges(
            "classify_intent",
            self.route_from_classify,
            {
                "news_query":           "search_news",
                "format_for_linkedin":  "format_for_linkedin",
                "format_for_facebook":  "format_for_facebook",
                "news_then_post":       "search_news",
                "other":                "handle_error",
            },
        )

        workflow.add_edge("search_news",   "filter_news")
        workflow.add_edge("filter_news",   "summarize_news")

        workflow.add_conditional_edges(
            "summarize_news",
            self._route_after_summarize,
            {
                "await_confirmation": "await_confirmation",
                "prepare_response":   "prepare_response",
            },
        )

        workflow.add_edge("await_confirmation", END)

        workflow.add_conditional_edges(
            "check_confirmation",
            self._route_after_confirmation,
            {
                "format_for_linkedin": "format_for_linkedin",
                "format_for_facebook": "format_for_facebook",
                "prepare_response":    "prepare_response",
            },
        )

        workflow.add_conditional_edges(
            "format_for_linkedin",
            self._route_format_to_post,
            {
                "post_to_linkedin": "post_to_linkedin",
                "prepare_response": "prepare_response",
            },
        )

        workflow.add_conditional_edges(
            "format_for_facebook",
            self._route_format_to_post,
            {
                "post_to_facebook": "post_to_facebook",
                "prepare_response": "prepare_response",
            },
        )

        workflow.add_edge("post_to_linkedin",  "store_results")
        workflow.add_edge("post_to_facebook",  "store_results")
        workflow.add_edge("store_results",     "prepare_response")
        workflow.add_edge("prepare_response",  END)
        workflow.add_edge("handle_error",      "prepare_response")

        return workflow.compile()

    def _build_resume_graph(self):
        """Pre‑compiled sub‑graph for resuming after confirmation."""
        sub = StateGraph(AgentState)
        sub.add_node("check_confirmation",  self.check_confirmation)
        sub.add_node("format_for_linkedin", self.format_for_linkedin)
        sub.add_node("format_for_facebook", self.format_for_facebook)
        sub.add_node("post_to_linkedin",    self.post_to_linkedin)
        sub.add_node("post_to_facebook",    self.post_to_facebook)
        sub.add_node("store_results",       self.store_results)
        sub.add_node("prepare_response",    self.prepare_response)

        sub.set_entry_point("check_confirmation")
        sub.add_conditional_edges(
            "check_confirmation",
            self._route_after_confirmation,
            {
                "format_for_linkedin": "format_for_linkedin",
                "format_for_facebook": "format_for_facebook",
                "prepare_response":    "prepare_response",
            },
        )

        sub.add_conditional_edges(
            "format_for_linkedin",
            self._route_format_to_post,
            {
                "post_to_linkedin": "post_to_linkedin",
                "prepare_response": "prepare_response",
            },
        )

        sub.add_conditional_edges(
            "format_for_facebook",
            self._route_format_to_post,
            {
                "post_to_facebook": "post_to_facebook",
                "prepare_response": "prepare_response",
            },
        )

        sub.add_edge("post_to_linkedin",  "store_results")
        sub.add_edge("post_to_facebook",  "store_results")
        sub.add_edge("store_results",     "prepare_response")
        sub.add_edge("prepare_response",  END)
        return sub.compile()

    # ── Routing helpers ───────────────────────────────────────────────────────

    def _route_after_summarize(self, state: AgentState) -> str:
        if state["intent"] == "news_then_post":
            return "await_confirmation"
        return "prepare_response"

    def _route_after_confirmation(self, state: AgentState) -> str:
        if not state.get("confirmed"):
            return "prepare_response"
        
        platform = state.get("target_platform", "linkedin")
        if platform == "facebook":
            return "format_for_facebook"
        return "format_for_linkedin"

    def _route_format_to_post(self, state: AgentState) -> str:
        """Route from format node to appropriate post node or error handler."""
        if state.get("error"):
            return "prepare_response"
        
        platform = state.get("target_platform", "linkedin")
        if platform == "facebook":
            return "post_to_facebook"
        return "post_to_linkedin"

    # ── Node implementations ──────────────────────────────────────────────────

    async def classify_intent(self, state: AgentState) -> AgentState:
        try:
            state["intent"] = await self.intent_agent.classify(state["query"])
            state["target_platform"] = await self.intent_agent.detect_platform(state["query"])
        except Exception as exc:
            logger.error("classify_intent failed: %s", exc)
            state["error"]  = str(exc)
            state["intent"] = "other"
            state["target_platform"] = "linkedin"
        return state

    def route_by_intent(self, state: AgentState) -> str:
        if state.get("error"):
            return "other"
        
        intent = state.get("intent", "other")
        # For post_request, route based on platform
        if intent == "post_request":
            platform = state.get("target_platform", "linkedin")
            if platform == "facebook":
                return "post_request"  # Will be handled separately
            return "post_request"  # Default to LinkedIn
        
        return intent

    def route_from_classify(self, state: AgentState) -> str:
        """Route after intention classification, considering target platform."""
        if state.get("error"):
            return "other"
        
        intent = state.get("intent", "other")
        platform = state.get("target_platform", "linkedin")
        
        if intent == "post_request":
            # Route to appropriate formatter based on platform
            if platform == "facebook":
                return "format_for_facebook"
            return "format_for_linkedin"
        
        return intent

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
            filtered = NewsFilterAgent.filter_tech_news(state["search_results"])
            if not filtered:
                logger.warning("No tech articles after filtering – keeping all results")
                filtered = state["search_results"]
            state["filtered_news"] = filtered
        except Exception as exc:
            logger.error("filter_news failed: %s", exc)
            state["error"]         = f"Filtering failed: {exc}"
            state["filtered_news"] = state.get("search_results", [])
        return state

    async def summarize_news(self, state: AgentState) -> AgentState:
        summaries: list[str] = []
        articles = state.get("filtered_news", [])[:3]

        for article in articles:
            try:
                summary = await self.summarizer.summarize(article)
                if summary:
                    summaries.append(summary)
                await MemoryAgent.store_news_article(article)
            except Exception as exc:
                logger.warning(
                    "Could not summarise article %r: %s",
                    article.get("title", "?"),
                    exc,
                )

        if not summaries:
            state["error"] = "Could not summarise any articles."

        state["summaries"]     = summaries
        state["news_preview"]  = articles
        return state

    async def await_confirmation(self, state: AgentState) -> AgentState:
        summaries = state.get("summaries", [])
        articles  = state.get("news_preview", [])
        platform = state.get("target_platform", "LinkedIn").title()

        if not summaries:
            state["awaiting_confirmation"] = False
            state["confirmed"]             = False
            state["error"]                 = "No summaries to post."
            return state

        preview_lines = []
        for i, (article, summary) in enumerate(zip(articles, summaries), start=1):
            title  = article.get("title", "Untitled")
            source = article.get("source", article.get("url", ""))
            preview_lines.append(
                f" **{i}. {title}**\n"
                f"   Source: {source}\n"
                f"   {summary}\n"
            )

        preview_text = "\n".join(preview_lines)

        state["user_response"] = (
            f"🔍 **Here's what I found — shall I post this to {platform}?**\n\n"
            f"{preview_text}\n"
            "---\n"
            "Reply **yes** to post, or **no** to cancel."
        )
        state["awaiting_confirmation"] = True
        state["confirmed"]             = False

        logger.info("Pausing for user confirmation before %s post", platform)
        return state

    async def check_confirmation(self, state: AgentState) -> AgentState:
        confirmed = state.get("confirmed", False)
        logger.info("User confirmation received: %s", confirmed)
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
            # Format for Facebook (simpler formatting, shorter posts)
            formatted = await self.formatter.format_for_linkedin(summaries)  # Use same formatter for now
            if not formatted:
                raise ValueError("Formatter returned empty content")
            state["formatted_content"] = formatted
        except Exception as exc:
            logger.error("format_for_facebook failed: %s", exc)
            state["error"]             = f"Formatting failed: {exc}"
            state["formatted_content"] = state["query"]
        return state

    async def post_to_linkedin(self, state: AgentState) -> AgentState:
        try:
            result = await LinkedInAgent.post(state["formatted_content"])
            state["post_result"] = result
        except Exception as exc:
            logger.error("post_to_linkedin failed: %s", exc)
            state["post_result"] = {"success": False, "error": str(exc)}
        return state

    async def post_to_facebook(self, state: AgentState) -> AgentState:
        try:
            result = await FacebookAgent.post(state["formatted_content"])
            state["post_result"] = result
        except Exception as exc:
            logger.error("post_to_facebook failed: %s", exc)
            state["post_result"] = {"success": False, "error": str(exc)}
        return state

    async def store_results(self, state: AgentState) -> AgentState:
        try:
            await MemoryAgent.store_post_result(
                state.get("query_id"),
                state["formatted_content"],
                state["post_result"],
            )
        except Exception as exc:
            logger.error("store_results failed (non-fatal): %s", exc)
        return state

    async def prepare_response(self, state: AgentState) -> AgentState:
        intent         = state.get("intent", "other")
        error          = state.get("error", "")
        summaries      = state.get("summaries", [])
        post_result    = state.get("post_result", {})
        platform       = state.get("target_platform", "LinkedIn").title()
        summaries_text = "\n\n".join(summaries) if summaries else "No summaries available."
        post_success   = post_result.get("success", False)
        post_error     = post_result.get("error", "Unknown error")

        if intent == "news_then_post" and not state.get("confirmed") and summaries:
            state["user_response"] = (
                "Got it — not posting. Here are the summaries anyway:\n\n"
                f"{summaries_text}"
            )
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
                # ✅ Return the actual formatted post content
                state["user_response"] = state.get("formatted_content", f"Posted successfully to {platform}")
            else:
                state["user_response"] = (
                    f"News fetched but posting to {platform} failed: {post_error}\n\n"
                    f"**Summaries:**\n{summaries_text}"
                )
        else:
            state["user_response"] = (
                "I can only help with tech news queries or social media posts (LinkedIn/Facebook). "
                "Try: 'What's the latest in AI?' or 'Find AI news and post it on Facebook'."
            )

        try:
            query_id = await MemoryAgent.store_query(
                state["query"], intent, state["user_response"]
            )
            state["query_id"] = query_id
        except Exception as exc:
            logger.error("Failed to store query (non-fatal): %s", exc)

        return state

    async def handle_error(self, state: AgentState) -> AgentState:
        if not state.get("error"):
            state["error"] = (
                "Unrecognised request. "
                "Please ask about tech news or LinkedIn posting."
            )
        return state

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self, query: str) -> str:
        query = (query or "").strip()
        if not query:
            return "Please provide a query."

        state = self._initial_state(query)
        try:
            final = await self.graph.ainvoke(state)
            return final["user_response"]
        except Exception as exc:
            logger.critical("Graph execution failed: %s", exc, exc_info=True)
            return f"Unexpected error: {exc}"

    async def run_with_confirmation(self, query: str) -> AgentState:
        query = (query or "").strip()
        if not query:
            return {"user_response": "Please provide a query.", "awaiting_confirmation": False}

        state = self._initial_state(query)
        try:
            return await self.graph.ainvoke(state)
        except Exception as exc:
            logger.critical("Graph execution failed: %s", exc, exc_info=True)
            return {"user_response": f"Unexpected error: {exc}", "awaiting_confirmation": False}

    async def resume(self, state: AgentState, confirmed: bool) -> AgentState:
        state["confirmed"]             = confirmed
        state["awaiting_confirmation"] = False

        try:
            return await self._resume_graph.ainvoke(state)
        except Exception as exc:
            logger.critical("Resume failed: %s", exc, exc_info=True)
            state["user_response"] = f"Unexpected error during resume: {exc}"
            return state

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