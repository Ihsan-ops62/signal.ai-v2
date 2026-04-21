"""
Main FastAPI application for Signal AI.
"""
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from agents.audio.audio_agent import VoicePipelineSession
from agents.memory.memory_agent import MemoryAgent
from agents.conversation.conversation_agent import ConversationAgent
from agents.graph.workflow import NewsReporterGraph
from core.config import settings
from infrastructure.monitoring.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Global instances (initialized at startup)
graph = None
conversation_agent = None
whisper_model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    global graph, conversation_agent, whisper_model

    logger.info("Starting Signal AI application")

    # Connect to MongoDB
    from infrastructure.database.mongodb import MongoDB
    await MongoDB.connect()

    # Initialize LangGraph workflow
    graph = NewsReporterGraph()

    # Initialize ConversationAgent with the graph
    conversation_agent = ConversationAgent(graph)

    # Initialize Whisper model for voice
    from faster_whisper import WhisperModel
    whisper_model = WhisperModel("small", device="cpu", compute_type="int8")

    logger.info("All agents and models loaded")

    yield

    logger.info("Shutting down Signal AI application")
    await MongoDB.close()


def create_app() -> FastAPI:
    """Create FastAPI application."""
    app = FastAPI(
        title="Signal AI",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        response.headers["X-Process-Time"] = str(time.time() - start_time)
        return response

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})

    # Import and include REST routes
    from api.routes import auth, chat, social, admin, webhooks

    # Mount routers with correct prefixes to match frontend expectations
    app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])

    # Chat router mounted directly under /api (provides /api/sessions, /api/stats, /api/chat, etc.)
    app.include_router(chat.router, prefix="/api", tags=["Chat"])

    # Social router mounted directly under /api (provides /api/user/connections, etc.)
    app.include_router(social.router, prefix="/api", tags=["Social"])

    # Admin router under /api/admin (provides /api/admin/stats, etc.)
    app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])

    # Webhooks router
    app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])

    # Static files and frontend
    BASE_DIR = Path(__file__).resolve().parent.parent
    STATIC_DIR = BASE_DIR / "static"
    INDEX_PATH = BASE_DIR / "index.html"
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/")
    async def serve_frontend():
        if INDEX_PATH.exists():
            return FileResponse(str(INDEX_PATH), media_type="text/html")
        raise HTTPException(status_code=404, detail="Frontend not found")

    # ------------------------------------------------------------------
    # WebSocket Endpoint
    # ------------------------------------------------------------------
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        authenticated_user = None

        try:
            # Authenticate via token
            auth_msg = await websocket.receive_json()
            token_val = auth_msg.get("token")
            if not token_val:
                await websocket.send_json({"type": "error", "message": "Missing token"})
                await websocket.close()
                return

            from jose import jwt, JWTError
            from core.config import settings as config_settings
            SECRET_KEY = config_settings.SECRET_KEY
            ALGORITHM = "HS256"

            try:
                payload = jwt.decode(token_val, SECRET_KEY, algorithms=[ALGORITHM])
                user_id = payload.get("sub")
                if not user_id:
                    raise JWTError()
            except JWTError:
                await websocket.send_json({"type": "error", "message": "Invalid token"})
                await websocket.close()
                return

            # Verify user exists in MongoDB
            from infrastructure.database.mongodb import MongoDB
            from bson import ObjectId
            users_coll = MongoDB.get_collection("users")
            try:
                obj_id = ObjectId(user_id)
            except:
                await websocket.send_json({"type": "error", "message": "Invalid user ID"})
                await websocket.close()
                return

            user_doc = await users_coll.find_one({"_id": obj_id})
            if not user_doc:
                await websocket.send_json({"type": "error", "message": "User not found"})
                await websocket.close()
                return

            authenticated_user = {
                "id": str(user_doc["_id"]),
                "email": user_doc.get("email"),
                "name": user_doc.get("name"),
                "username": user_doc.get("email"),  # for compatibility
            }

            await websocket.send_json({"type": "auth_ok"})
            logger.info("WebSocket authenticated for user %s", authenticated_user["email"])

        except WebSocketDisconnect:
            return
        except Exception as e:
            logger.error("WebSocket auth error: %s", e)
            await websocket.close()
            return

        # Main message loop
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")
                session_id = data.get("session_id") or authenticated_user["id"]

                if msg_type == "chat":
                    message = data["message"]
                    voice_mode = data.get("voice_mode", False)
                    logger.info("WS chat from %s: %s", authenticated_user["email"], message[:50])

                    async def send_progress(step: str, message_text: str):
                        try:
                            await websocket.send_json({
                                "type": "progress",
                                "step": step,
                                "message": message_text,
                            })
                        except Exception:
                            pass

                    try:
                        async for token_chunk in conversation_agent.chat_stream(
                            message,
                            session_id,
                            voice_mode,
                            progress_callback=send_progress,
                            user_id=authenticated_user["id"],
                        ):
                            await websocket.send_json({"type": "token", "content": token_chunk})
                        await websocket.send_json({"type": "end"})
                    except Exception as ex:
                        logger.exception("Error in chat_stream: %s", ex)
                        await websocket.send_json({"type": "error", "message": str(ex)})

                elif msg_type == "voice":
                    if whisper_model is None:
                        await websocket.send_json({"type": "error", "message": "Whisper model not loaded"})
                        continue
                    session = VoicePipelineSession(
                        websocket,
                        whisper_model,
                        conversation_agent,
                        session_id,
                        voice_mode=True
                    )
                    await session.run()
                    break  # Voice session takes over the connection

                elif msg_type == "stop":
                    await websocket.send_json({"type": "stopped"})

                elif msg_type == "new_chat":
                    conversation_agent.clear_context(session_id)
                    await websocket.send_json({"type": "new_chat_ok"})

                elif msg_type == "load_session":
                    context = await MemoryAgent.load_context(session_id)
                    await websocket.send_json({
                        "type": "session_loaded",
                        "session_id": session_id,
                        "context": context,
                    })

                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected for user %s", authenticated_user["email"] if authenticated_user else "unknown")

    return app


app = create_app()