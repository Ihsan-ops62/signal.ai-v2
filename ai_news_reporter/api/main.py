import uuid
import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from graph.workflow import NewsReporterGraph
from database.mongodb_client import MongoDB
from logging_config import setup_logging
from api.schemas import QueryRequest, QueryResponse, ConfirmRequest, ConfirmResponse

setup_logging()
logger = logging.getLogger(__name__)

# ── In-memory session store ───────────────────────────────────────────────────
# Holds paused AgentState objects while we wait for the user to confirm/deny.
# Keys are UUIDs returned to the client as `session_id`.
# In production, swap this dict for Redis with a short TTL (e.g. 10 minutes).
_pending_sessions: dict[str, dict] = {}


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await MongoDB.connect()
    global graph
    graph = NewsReporterGraph()
    logger.info("NewsReporterGraph ready")
    yield
    await MongoDB.close()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="AI News Reporter System", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # FIXED: Cannot be True when allow_origins is ["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

graph: NewsReporterGraph | None = None   # set during startup


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse)
async def handle_query(req: QueryRequest):
    """
    Run the agent pipeline for a user query.

    - For `news_query` and `post_request` intents the pipeline runs to
      completion and returns the final answer immediately.
    - For `news_then_post` the pipeline pauses after summarisation and
      returns a preview with `awaiting_confirmation=True`. The client must
      then call POST /confirm.
    """
    if graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialised yet")

    try:
        # Wrap with timeout (120 seconds)
        state = await asyncio.wait_for(
            graph.run_with_confirmation(req.query),
            timeout=120
        )
    except asyncio.TimeoutError:
        logger.error("Graph execution timed out after 120 seconds for query: %s", req.query)
        raise HTTPException(status_code=504, detail="Request timed out. The AI reporter is taking too long.")
    except Exception as exc:
        logger.exception("run_with_confirmation raised: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    # ── Helper to build preview from state ───────────────────────────────────
    def build_preview():
        articles = state.get("news_preview", [])
        summaries = state.get("summaries", [])
        return [
            {
                "title": art.get("title", "Untitled"),
                "source": art.get("source", art.get("url", "")),
                "summary": summaries[i] if i < len(summaries) else "",
            }
            for i, art in enumerate(articles)
        ]

    # ── Confirmation required ─────────────────────────────────────────────────
    if state.get("awaiting_confirmation"):
        session_id = str(uuid.uuid4())
        _pending_sessions[session_id] = state
        logger.info("Session %s waiting for confirmation", session_id)

        return QueryResponse(
            response=state.get("user_response", ""),
            awaiting_confirmation=True,
            session_id=session_id,
            news_preview=build_preview(),
        )

    # ── Pipeline finished in one shot (news_query or post_request) ───────────
    # Include news_preview if available (for news_query responses)
    news_preview = build_preview() if state.get("news_preview") else None

    return QueryResponse(
        response=state.get("user_response", ""),
        awaiting_confirmation=False,
        news_preview=news_preview,
    )


@app.post("/confirm", response_model=ConfirmResponse)
async def handle_confirm(req: ConfirmRequest):
    """
    Resume a paused `news_then_post` pipeline after user confirmation.

    Pass the `session_id` received from POST /query together with
    `confirmed: true` (post) or `confirmed: false` (cancel).
    """
    state = _pending_sessions.pop(req.session_id, None)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found or already consumed. Please run a new query.",
        )

    try:
        final = await graph.resume(state, confirmed=req.confirmed)
    except Exception as exc:
        logger.exception("graph.resume raised: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    post_ok = final.get("post_result", {}).get("success", False)
    return ConfirmResponse(
        response=final.get("user_response", ""),
        success=post_ok if req.confirmed else True,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "graph_ready": graph is not None}