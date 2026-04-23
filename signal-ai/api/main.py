import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from api.routes import auth, chat, social, admin, webhooks
from infrastructure.database.mongodb import MongoDB
from infrastructure.monitoring.logging import setup_logging
from services.llm.ollama import OllamaService
from agents.graph.workflow import NewsReporterGraph
from agents.conversation.conversation_agent import ConversationAgent
from agents.audio.audio_agent import WhisperModel

setup_logging()
logger = logging.getLogger(__name__)

whisper_model: Optional[WhisperModel] = None
graph: Optional[NewsReporterGraph] = None
conversation_agent: Optional[ConversationAgent] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    await MongoDB.connect()
    global graph, conversation_agent, whisper_model

    ollama = OllamaService()
    if not await ollama.health_check():
        logger.error("Ollama not reachable at %s", ollama.base_url)
    else:
        logger.info("Ollama health check passed")

    graph = NewsReporterGraph()
    conversation_agent = ConversationAgent(ollama, graph)
    whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    logger.info("All agents loaded")
    yield
    await MongoDB.close()

app = FastAPI(title="Signal.AI", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:8000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(social.router, prefix="/social", tags=["social"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])

# Serve frontend
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index_path = Path(__file__).parent / "static" / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)