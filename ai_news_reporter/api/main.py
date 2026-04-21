
import json
import time
import uuid
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Optional
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
import httpx
from jose import JWTError
import jwt

from graph.workflow import NewsReporterGraph
from agents.conversation_agent import ConversationAgent
from agents.audio_agent import VoicePipelineSession
from database.mongodb_client import MongoDB
from logging_config import setup_logging
from api.schemas import (
    QueryRequest, QueryResponse, ConfirmRequest, ConfirmResponse,
    ChatRequest, ChatResponse,
)
from services.ollama_service import OllamaService
from services.oauth_service import (
    get_linkedin_auth_url,
    exchange_linkedin_code,
    create_oauth_state,
    validate_oauth_state,
    delete_token,
    load_token,
    store_token,
)
from services.linkedin_service import LinkedInService
from services.twitter_service import TwitterService
from auth.auth_file import (
    ALGORITHM, SECRET_KEY, Token, User, get_current_active_user, get_user,
    authenticate_user, create_access_token, get_password_hash,
    ACCESS_TOKEN_EXPIRE_MINUTES, oauth2_scheme,
)
from agents.memory_agent import MemoryAgent
from faster_whisper import WhisperModel

import os
# LangSmith integration
if os.getenv("LANGCHAIN_API_KEY"):
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", "ai-news-reporter")
    try:
        import langsmith  # noq
    except ImportError:
        pass

setup_logging()
logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS: int = 60000000
_pending_sessions: dict[str, tuple[dict, float]] = {}

whisper_model: Optional[WhisperModel] = None
graph: Optional[NewsReporterGraph] = None
conversation_agent: Optional[ConversationAgent] = None

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()] or [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    await MongoDB.connect()
    global graph, conversation_agent, whisper_model

    ollama_service = OllamaService()
    if not await ollama_service.health_check():
        logger.error("Ollama is not reachable at %s", ollama_service.base_url)
        logger.error(
            "Please start Ollama: 'ollama serve' and pull model: 'ollama pull %s'",
            ollama_service.model,
        )
    else:
        logger.info("Ollama health check passed")

    graph = NewsReporterGraph()
    conversation_agent = ConversationAgent(ollama_service, graph)
    whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    logger.info("All agents and models loaded")
    yield
    await MongoDB.close()

app = FastAPI(title="AI News Reporter", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# static frontend
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    for candidate in [
        Path(__file__).parent / "index.html",
        Path(__file__).parent / "static" / "index.html",
    ]:
        if candidate.exists():
            return FileResponse(candidate)
    return HTMLResponse(
        "<h1>Frontend not found. Place index.html in the project root.</h1>",
        status_code=404,
    )

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# auth endpoints
@app.post("/auth/register")
async def register(
    username: str,
    password: str,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
):
    collection = MongoDB.get_collection("users")
    existing = await collection.find_one({"username": username})
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")
    hashed = get_password_hash(password)
    await collection.insert_one({
        "username": username, "email": email, "full_name": full_name,
        "hashed_password": hashed, "disabled": False,
    })
    return {"message": "User created successfully"}

@app.post("/auth/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/auth/logout")
async def logout(
    current_user: User = Depends(get_current_active_user),
    token: str = Depends(oauth2_scheme),
):
    coll = MongoDB.get_collection("token_blacklist")
    from jose import jwt
    from auth.auth_file import SECRET_KEY, ALGORITHM
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp = payload.get("exp", int(time.time()) + 3600)
    except Exception:
        exp = int(time.time()) + 3600
    await coll.update_one(
        {"token": token},
        {"$set": {
            "token": token,
            "username": current_user.username,
            "blacklisted_at": time.time(),
            "expires_at": exp,
        }},
        upsert=True,
    )
    logger.info("Token blacklisted for user %s", current_user.username)
    return {"message": "Logged out successfully"}

@app.get("/auth/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user

# linkedin oauth
@app.get("/auth/linkedin/connect")
async def linkedin_connect(current_user: User = Depends(get_current_active_user)):
    try:
        state = create_oauth_state(current_user.username)
        auth_url = get_linkedin_auth_url(state)
        return {"auth_url": auth_url}
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/auth/linkedin/callback")
async def linkedin_callback(code: str, state: str):
    username = validate_oauth_state(state)
    if not username:
        return RedirectResponse(url=f"{FRONTEND_URL}?linkedin_error=invalid_state")
    result = await exchange_linkedin_code(code, username)
    if not result.get("success"):
        err = str(result.get("error", "unknown")).replace(" ", "_")[:60]
        return RedirectResponse(url=f"{FRONTEND_URL}?linkedin_error={err}")
    return RedirectResponse(url=f"{FRONTEND_URL}?linkedin_connected=true")

@app.delete("/auth/linkedin/disconnect")
async def linkedin_disconnect(current_user: User = Depends(get_current_active_user)):
    await delete_token(current_user.username, "linkedin")
    return {"status": "disconnected", "platform": "linkedin"}

# twitter oauth
@app.get("/auth/twitter/connect")
async def twitter_connect(current_user: User = Depends(get_current_active_user)):
    """
    Generates the OAuth 2.0 authorization URL for Twitter using PKCE.
    """
    try:
        state, code_verifier = TwitterService.create_pkce_state(current_user.username)
        auth_url = TwitterService.get_auth_url(state, code_verifier)
        return {"auth_url": auth_url}
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/auth/twitter/callback")
async def twitter_callback(code: str, state: str):
    """
    Handles the callback from Twitter after user authorization.
    Exchanges the auth code for access and refresh tokens.
    """
    validation_result = TwitterService.validate_pkce_state(state)
    if not validation_result:
        return RedirectResponse(url=f"{FRONTEND_URL}?twitter_error=invalid_state")

    username, code_verifier = validation_result
    result = await TwitterService.exchange_code(code, username, code_verifier)

    if not result.get("success"):
        err = str(result.get("error", "unknown")).replace(" ", "_")[:60]
        return RedirectResponse(url=f"{FRONTEND_URL}?twitter_error={err}")
    return RedirectResponse(url=f"{FRONTEND_URL}?twitter_connected=true")

@app.delete("/auth/twitter/disconnect")
async def twitter_disconnect(current_user: User = Depends(get_current_active_user)):
    await delete_token(current_user.username, "twitter")
    return {"status": "disconnected", "platform": "twitter"}

# mannual token endpoint
@app.post("/auth/linkedin/manual-token")
async def linkedin_manual_token(
    access_token: str,
    current_user: User = Depends(get_current_active_user),
):
    """Allow user to manually provide a LinkedIn access token."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Invalid LinkedIn access token")
        data = resp.json()
        sub = data.get("sub")
        if not sub:
            raise HTTPException(status_code=400, detail="Token lacks required 'sub' field")
        person_urn = f"urn:li:person:{sub}"
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token validation failed: {str(e)}")

    expires_in = 60 * 24 * 3600
    token_data = {
        "access_token": access_token,
        "expires_at": str(time.time() + expires_in),
        "token_type": "Bearer",
        "person_urn": person_urn,
    }
    await store_token(current_user.username.lower(), "linkedin", token_data)
    return {"status": "connected", "platform": "linkedin"}

@app.post("/auth/facebook/manual-token")
async def facebook_manual_token(
    access_token: str,
    page_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Store a Facebook Page Access Token + Page ID manually."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://graph.facebook.com/v20.0/{page_id}",
                params={"access_token": access_token, "fields": "id,name"}
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Invalid Facebook token or page ID")
        data = resp.json()
        if data.get("id") != page_id:
            raise HTTPException(status_code=400, detail="Page ID mismatch")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Validation failed: {str(e)}")

    token_data = {
        "access_token": access_token,
        "page_id": page_id,
        "expires_at": str(time.time() + 60 * 24 * 3600),
        "token_type": "Bearer",
    }
    await store_token(current_user.username.lower(), "facebook", token_data)
    return {"status": "connected", "platform": "facebook"}

@app.post("/auth/twitter/manual-token")
async def twitter_manual_token(
    access_token: str,
    current_user: User = Depends(get_current_active_user),
):
  
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.twitter.com/2/users/me",
                headers={"Authorization": f"Bearer {access_token}"}
            )
        
        if resp.status_code == 403:
            error_detail = resp.json().get("detail", "")
            if "oauth2" in error_detail.lower():
                raise HTTPException(
                    status_code=400,
                    detail="Token is invalid or missing required scopes. "
                           "Please generate a token with scopes: tweet.read, tweet.write, users.read, offline.access. "
                           "Alternatively, use the OAuth flow by clicking 'Connect Twitter' in Settings."
                )
            else:
                raise HTTPException(status_code=400, detail=f"Twitter API error: {error_detail}")
        
        if resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid Twitter access token (HTTP {resp.status_code}). Please check your token."
            )
        
        user_data = resp.json().get("data", {})
        user_id = user_data.get("id")
        if not user_id:
            raise HTTPException(status_code=400, detail="Token does not identify a Twitter user.")
            
    except httpx.RequestError as e:
        raise HTTPException(status_code=400, detail=f"Network error validating token: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Validation failed: {str(e)}")

    token_data = {
        "access_token": access_token,
        "expires_at": str(time.time() + 7200),
        "token_type": "Bearer",
        "twitter_user_id": user_id,
    }
    await store_token(current_user.username.lower(), "twitter", token_data)
    return {"status": "connected", "platform": "twitter", "user_id": user_id}

# disconnect endpoints for manual tokens
@app.delete("/auth/facebook/disconnect")
async def facebook_disconnect(current_user: User = Depends(get_current_active_user)):
    await delete_token(current_user.username, "facebook")
    return {"status": "disconnected"}

@app.delete("/linkedin/posts/{post_id}")
async def delete_linkedin_post(
    post_id: str,
    current_user: User = Depends(get_current_active_user),
):
    result = await LinkedInService.delete_post(post_id, username=current_user.username)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))
    return {"status": "deleted", "post_id": post_id}

# user connections status
@app.get("/user/connections")
async def get_user_connections(current_user: User = Depends(get_current_active_user)):
    def _status(record):
        if not record:
            return {"connected": False, "valid": False}
        exp = record.get("expires_at")
        valid = True
        if exp:
            try:
                # If exp is a Fernet encrypted string (starts with gAAAAA), it's corrupted
                if isinstance(exp, str) and exp.startswith('gAAAAA'):
                    logger.warning(f"Token for {current_user.username} has encrypted expiry – key mismatch")
                    return {"connected": True, "valid": False, "error": "Token encryption mismatch"}
                # Otherwise convert to float
                exp_float = float(exp)
                valid = exp_float > time.time()
            except (ValueError, TypeError):
                valid = False
        return {"connected": True, "valid": valid}
    
    li = await load_token(current_user.username, "linkedin")
    fb = await load_token(current_user.username, "facebook")
    tw = await load_token(current_user.username, "twitter")
    return {
        "linkedin": _status(li),
        "facebook": _status(fb),
        "twitter": _status(tw),
    }

@app.delete("/user/token/linkedin")
async def delete_linkedin_token(current_user: User = Depends(get_current_active_user)):
    await delete_token(current_user.username, "linkedin")
    return {"status": "ok"}

# stats
@app.get("/stats")
async def get_stats(current_user: User = Depends(get_current_active_user)):
    queries_coll = MongoDB.get_collection("queries")
    posts_coll = MongoDB.get_collection("posts")
    query_count = await queries_coll.count_documents({"user_id": current_user.username})
    post_count = await posts_coll.count_documents({"user_id": current_user.username, "status": "success"})
    li_posts = await posts_coll.count_documents({"user_id": current_user.username, "platform": "linkedin", "status": "success"})
    fb_posts = await posts_coll.count_documents({"user_id": current_user.username, "platform": "facebook", "status": "success"})
    tw_posts = await posts_coll.count_documents({"user_id": current_user.username, "platform": "twitter", "status": "success"})
    return {
        "queries": query_count,
        "posts": post_count,
        "platforms": {"linkedin": li_posts, "facebook": fb_posts, "twitter": tw_posts},
    }

# health check
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "graph_ready": graph is not None,
        "pending_sessions": len(_pending_sessions),
        "langsmith_enabled": bool(os.getenv("LANGCHAIN_API_KEY")),
    }

@app.get("/health/ollama")
async def check_ollama():
    if not conversation_agent:
        return {"status": "error", "detail": "Conversation agent not initialized"}
    try:
        service = OllamaService()
        ok = await service.health_check()
        if ok:
            return {"status": "ok", "model": service.model, "base_url": service.base_url}
        return {"status": "error", "detail": "Ollama not reachable or model missing"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

# core query handling
@app.post("/query", response_model=QueryResponse)
async def handle_query(
    req: QueryRequest,
    current_user: User = Depends(get_current_active_user),
):
    if graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialised yet")
    try:
        state = await asyncio.wait_for(
            graph.run_with_confirmation(req.query, username=current_user.username),
            timeout=60000.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Request timed out.")
    except Exception as exc:
        logger.exception("run_with_confirmation raised: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    articles = state.get("news_preview", [])
    summaries = state.get("summaries", [])
    preview = [
        {
            "title": a.get("title", ""),
            "source": a.get("source", a.get("url", "")),
            "summary": summaries[i] if i < len(summaries) else "",
            "url": a.get("url", ""),
        }
        for i, a in enumerate(articles)
    ]
    session_id = str(uuid.uuid4())
    _pending_sessions[session_id] = (dict(state), time.time())
    return QueryResponse(
        response=state.get("user_response", ""),
        awaiting_confirmation=state.get("awaiting_confirmation", False),
        session_id=session_id if state.get("awaiting_confirmation") else None,
        news_preview=preview,
        formatted_content=state.get("formatted_content"),
    )

@app.post("/confirm", response_model=ConfirmResponse)
async def confirm_query(
    req: ConfirmRequest,
    current_user: User = Depends(get_current_active_user),
):
    entry = _pending_sessions.pop(req.session_id, None)
    if not entry:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    state, created_at = entry
    if time.time() - created_at > SESSION_TTL_SECONDS:
        raise HTTPException(status_code=410, detail="Session expired.")
    try:
        final = await graph.resume(state, confirmed=req.confirmed, username=current_user.username)
    except Exception as exc:
        logger.exception("graph.resume raised: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    post_ok = final.get("post_result", {}).get("success", False)
    return ConfirmResponse(
        response=final.get("user_response", ""),
        success=post_ok if req.confirmed else True,
    )

# chat http fallback
@app.post("/chat", response_model=ChatResponse)
async def handle_chat(
    req: ChatRequest,
    current_user: User = Depends(get_current_active_user),
):
    if conversation_agent is None:
        raise HTTPException(status_code=503, detail="Conversation agent not initialised")
    try:
        logger.info("Chat request from %s: %s", current_user.username, req.message[:50])
        response = await asyncio.wait_for(
            conversation_agent.chat(
                req.message,
                session_id=req.session_id or current_user.username,
                user_id=current_user.username,
            ),
            timeout=4000.0,
        )
        action = conversation_agent.detect_action(req.message)
        return ChatResponse(response=response, action=action)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Request timed out.")
    except Exception as exc:
        logger.exception("Chat error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

# session history
@app.get("/sessions")
async def list_user_sessions(current_user: User = Depends(get_current_active_user)):
    coll = MongoDB.get_collection("contexts")
    cursor = coll.find({"user_id": current_user.username}).sort("updated_at", -1).limit(30)
    sessions = []
    async for doc in cursor:
        history = doc.get("history", [])
        preview = next(
            (m.get("message", "")[:60] for m in history if m.get("role") == "user"), ""
        )
        sessions.append({
            "session_id": doc["session_id"],
            "preview": preview,
            "updated_at": doc.get("updated_at").isoformat() if doc.get("updated_at") else None,
        })
    return {"sessions": sessions}

@app.delete("/session/{session_id}")
async def delete_user_session(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
    ):
    # Verify ownership and delete from contexts
    coll = MongoDB.get_collection("contexts")
    result = await coll.delete_one({"session_id": session_id, "user_id": current_user.username})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Session not found or not authorized")
        
    # Clean up any pending graph/agent state
    sessions_coll = MongoDB.get_collection("sessions")
    await sessions_coll.delete_one({"session_id": session_id})
    
    return {"status": "deleted", "session_id": session_id}

# websocket
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    authenticated_user: Optional[User] = None
    voice_session_active = False

    try:
        # Authenticate
        auth_msg = await websocket.receive_json()
        token_val = auth_msg.get("token")
        if not token_val:
            await websocket.send_json({"type": "error", "message": "Missing token"})
            await websocket.close()
            return

       
        try:
            payload = jwt.decode(token_val, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
            if not username:
                raise JWTError()
        except JWTError:
            await websocket.send_json({"type": "error", "message": "Invalid token"})
            await websocket.close()
            return

        user_db = await get_user(username)
        if not user_db:
            await websocket.send_json({"type": "error", "message": "User not found"})
            await websocket.close()
            return

        authenticated_user = User(
            username=user_db.username,
            email=user_db.email,
            full_name=user_db.full_name,
            disabled=user_db.disabled,
        )
        await websocket.send_json({"type": "auth_ok"})
        logger.info("WebSocket authenticated for user %s", authenticated_user.username)

        # Main message loop
        while True:
            try:
                # Receive with timeout to allow ping/pong
                msg = await asyncio.wait_for(websocket.receive(), timeout=60.0)
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break
                continue
            except (WebSocketDisconnect, RuntimeError) as e:
                # RuntimeError happens when receive is called after disconnect
                logger.debug("WebSocket receive stopped: %s", e)
                break

            # Handle binary messages (voice audio)
            if "bytes" in msg:
                # If voice session is not active, we cannot process
                # For now, ignore; voice session must be started via JSON
                continue

            # Handle text messages (JSON)
            if "text" not in msg:
                continue

            try:
                data = json.loads(msg["text"])
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")
            session_id = data.get("session_id") or authenticated_user.username

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "voice":
                if whisper_model is None:
                    await websocket.send_json({"type": "error", "message": "Whisper model not loaded"})
                    continue
                # Start voice session – it will take over receiving messages
                session = VoicePipelineSession(
                    websocket, whisper_model, conversation_agent, session_id
                )
                voice_session_active = True
                await session.run()
                voice_session_active = False
                # After voice session ends, continue the loop (do not break)
                continue

            if msg_type == "chat":
                message = data["message"]
                voice_mode = data.get("voice_mode", False)
                logger.info("WS chat from %s: %s", authenticated_user.username, message[:50])

                async def send_progress(step: str, message_text: str):
                    try:
                        if websocket.client_state.name == "CONNECTED":
                            await websocket.send_json({
                                "type": "progress",
                                "step": step,
                                "message": message_text,
                            })
                    except Exception as ex:
                        logger.warning("Failed to send progress: %s", ex)

                try:
                    async for token_chunk in conversation_agent.chat_stream(
                        message, session_id, voice_mode,
                        progress_callback=send_progress,
                        user_id=authenticated_user.username,
                    ):
                        if websocket.client_state.name != "CONNECTED":
                            break
                        await websocket.send_json({"type": "token", "content": token_chunk})
                    if websocket.client_state.name == "CONNECTED":
                        await websocket.send_json({"type": "end"})
                except Exception as ex:
                    logger.exception("Error in chat_stream: %s", ex)
                    try:
                        if websocket.client_state.name == "CONNECTED":
                            await websocket.send_json({"type": "error", "message": str(ex)})
                    except Exception:
                        pass

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

    except WebSocketDisconnect:
        logger.info(
            "WebSocket disconnected for user %s",
            authenticated_user.username if authenticated_user else "unknown",
        )
    except Exception as e:
        logger.exception("Unexpected WebSocket error: %s", e)
        try:
            await websocket.close()
        except:
            pass

#activity
@app.get("/activity")
async def get_recent_activity(
    current_user: User = Depends(get_current_active_user),
    limit: int = 20,
):
    activities = await MemoryAgent.get_recent_activities(
        user_id=current_user.username, limit=limit
    )
    return {"activities": activities}