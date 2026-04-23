import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends

from api.dependencies.auth import get_current_user_ws, get_current_active_user, User
from agents.conversation.conversation_agent import ConversationAgent
from agents.audio.audio_agent import VoicePipelineSession, WhisperModel
from agents.graph.workflow import NewsReporterGraph
from services.llm.ollama import OllamaService
from agents.memory.memory_agent import MemoryAgent
from services.cache.session_manager import SessionManager
from infrastructure.database.mongodb import MongoDB

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize Singletons
_whisper = WhisperModel("small", device="cpu", compute_type="int8")
_ollama = OllamaService()
_graph = NewsReporterGraph()
_conv_agent = ConversationAgent(_ollama, _graph)


# websocket endpoint for real-time chat and voice interactions

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Authenticate via the first JSON message
    user = await get_current_user_ws(websocket)
    if not user:
        return

    logger.info("WebSocket authenticated for user %s", user.username)

    async def send_progress(step: str, message: str):
        try:
            await websocket.send_json({"type": "progress", "step": step, "message": message})
        except Exception:
            pass 

    try:
        while True:
            try:
                msg = await websocket.receive_text()
                data = json.loads(msg)
            except WebSocketDisconnect:
                break

            msg_type = data.get("type")
            session_id = data.get("session_id") or user.username

            if msg_type == "voice":
                session = VoicePipelineSession(
                    websocket, _whisper, _conv_agent, session_id
                )
                await session.run()

            elif msg_type == "chat":
                message = data["message"]
                voice_mode = data.get("voice_mode", False)
                async for token in _conv_agent.chat_stream(
                    message,
                    session_id,
                    voice_mode,
                    progress_callback=send_progress,
                    user_id=user.username,
                ):
                    await websocket.send_json({"type": "token", "content": token})
                await websocket.send_json({"type": "end"})

            elif msg_type == "new_chat":
                await SessionManager.delete_session(session_id)
                await websocket.send_json({"type": "new_chat_ok"})

            elif msg_type == "load_session":
                # Fetch history from Persistent DB
                context = await MemoryAgent.load_context(session_id)
                await websocket.send_json({
                    "type": "session_loaded",
                    "session_id": session_id,
                    "context": context,
                })
    except Exception as e:
        logger.exception("WebSocket error: %s", e)


# rest endpoints for managing chat sessions and activity feed

@router.get("/sessions")
async def get_chat_sessions(current_user: User = Depends(get_current_active_user)):
    """Fetch chat history sessions for the left sidebar."""
    coll = MongoDB.get_collection("contexts")
    
    # Get the last 30 sessions for this specific user
    cursor = coll.find({"user_id": current_user.username}).sort("_id", -1).limit(30)
    docs = await cursor.to_list(length=30)
    
    sessions = []
    for doc in docs:
        history = doc.get("history", [])
        preview = "New Chat"
        if history:
            # Find first user message for the sidebar preview
            user_msgs = [m for m in history if m.get("role") == "user"]
            if user_msgs:
                preview = user_msgs[0].get("message", "")[:40] + "..."
                    
        sessions.append({
            "session_id": doc.get("session_id"),
            "preview": preview
        })
        
    return {"sessions": sessions}


@router.delete("/session/{session_id}")
async def delete_chat_session(session_id: str, current_user: User = Depends(get_current_active_user)):
    """Delete a specific chat session and clear its cache."""
    coll = MongoDB.get_collection("contexts")
    await coll.delete_one({"session_id": session_id, "user_id": current_user.username})
    
    # Also wipe from Redis so the agent doesn't "remember" the deleted chat
    await SessionManager.delete_session(session_id)
    return {"success": True}


@router.get("/activity")
async def get_recent_activity(limit: int = 15, current_user: User = Depends(get_current_active_user)):
    """Fetch recent social posts and queries for the right sidebar trace."""
    activities = await MemoryAgent.get_recent_activities(user_id=current_user.username, limit=limit)
    return {"activities": activities}