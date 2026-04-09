import io
import os
import time
import uuid
import logging
import asyncio
import tempfile
from contextlib import asynccontextmanager

import edge_tts                         # pip install edge-tts
from faster_whisper import WhisperModel  # pip install faster-whisper

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from graph.workflow import NewsReporterGraph
from agents.conversation_agent import ConversationAgent
from database.mongodb_client import MongoDB
from logging_config import setup_logging
from api.schemas import (
    QueryRequest, QueryResponse,
    ConfirmRequest, ConfirmResponse,
    ChatRequest, ChatResponse,
    TTSRequest, STTResponse,
)
from services.ollama_service import OllamaService

setup_logging()
logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS: int = 600
_pending_sessions: dict[str, tuple[dict, float]] = {}

# ── Whisper model (loaded once at startup) ─────────────────────────────────────
# Model sizes: "tiny", "base", "small", "medium", "large-v3"
# Use "base" for fast CPU inference. Switch to "small" or "medium" for accuracy.
_WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")
_whisper: WhisperModel | None = None


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph, conversation_agent, _whisper

    await MongoDB.connect()

    graph              = NewsReporterGraph()
    conversation_agent = ConversationAgent(OllamaService(), graph)

    # Load Whisper on a thread so we don't block the event loop
    loop = asyncio.get_event_loop()
    _whisper = await loop.run_in_executor(
        None,
        lambda: WhisperModel(_WHISPER_MODEL_SIZE, device="cpu", compute_type="int8"),
    )

    logger.info("NewsReporterGraph        ready")
    logger.info("ConversationAgent        ready")
    logger.info("Whisper (%s)             ready", _WHISPER_MODEL_SIZE)

    yield

    await MongoDB.close()


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Signal.AI — Voice Tech Reporter", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

graph:              NewsReporterGraph  | None = None
conversation_agent: ConversationAgent | None = None


# ── /query ─────────────────────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse)
async def handle_query(req: QueryRequest):
    if graph is None:
        raise HTTPException(503, "Graph not initialised yet")
    try:
        state = await asyncio.wait_for(
            graph.run_with_confirmation(req.query), timeout=600
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, "Request timed out.")
    except Exception as exc:
        logger.exception("run_with_confirmation: %s", exc)
        raise HTTPException(500, str(exc))

    def build_preview() -> list[dict]:
        arts  = state.get("news_preview", [])
        sums  = state.get("summaries", [])
        return [
            {
                "title":   a.get("title", "Untitled"),
                "source":  a.get("source", a.get("url", "")),
                "summary": sums[i] if i < len(sums) else "",
            }
            for i, a in enumerate(arts)
        ]

    if state.get("awaiting_confirmation"):
        sid = str(uuid.uuid4())
        _pending_sessions[sid] = (state, time.monotonic())
        return QueryResponse(
            response=state.get("user_response", ""),
            awaiting_confirmation=True,
            session_id=sid,
            news_preview=build_preview(),
        )

    return QueryResponse(
        response=state.get("user_response", ""),
        awaiting_confirmation=False,
        news_preview=build_preview() if state.get("news_preview") else None,
    )


# ── /confirm ───────────────────────────────────────────────────────────────────

@app.post("/confirm", response_model=ConfirmResponse)
async def handle_confirm(req: ConfirmRequest):
    entry = _pending_sessions.pop(req.session_id, None)
    if entry is None:
        raise HTTPException(404, "Session not found or expired.")
    state, created_at = entry
    if time.monotonic() - created_at > SESSION_TTL_SECONDS:
        raise HTTPException(410, "Session expired. Please run a new query.")
    try:
        final = await graph.resume(state, confirmed=req.confirmed)
    except Exception as exc:
        logger.exception("graph.resume: %s", exc)
        raise HTTPException(500, str(exc))
    post_ok = final.get("post_result", {}).get("success", False)
    return ConfirmResponse(
        response=final.get("user_response", ""),
        success=post_ok if req.confirmed else True,
    )


# ── /chat ──────────────────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def handle_chat(req: ChatRequest):
    if conversation_agent is None:
        raise HTTPException(503, "Conversation agent not initialised yet")
    try:
        response = await asyncio.wait_for(
            conversation_agent.chat(
                req.message,
                session_id=req.session_id,
                voice_mode=req.voice_mode,
            ),
            timeout=400.0,
        )
        action = conversation_agent.detect_action(req.message)
        return ChatResponse(
            response=response,
            action=action,
            voice_text=response if req.voice_mode else None,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, "Request timed out.")
    except Exception as exc:
        logger.exception("Chat error: %s", exc)
        raise HTTPException(500, str(exc))


# ── /tts  (Text → MP3 audio stream) ───────────────────────────────────────────

@app.post(
    "/tts",
    summary="Text-to-speech using Edge-TTS",
    response_class=StreamingResponse,
    responses={200: {"content": {"audio/mpeg": {}}}},
)
async def text_to_speech(req: TTSRequest):
    """
    Convert text to speech using Microsoft Edge-TTS (free, no API key needed).
    Returns an MP3 audio stream.

    Popular voice names:
      en-US-AriaNeural   — warm US English female (default)
      en-US-GuyNeural    — US English male
      en-GB-SoniaNeural  — British English female
      en-AU-NatashaNeural — Australian female
    """
    if not req.text.strip():
        raise HTTPException(400, "Text cannot be empty.")

    # Truncate to 2000 chars – Edge-TTS handles long text poorly in one shot
    text = req.text.strip()[:2000]

    try:
        communicate = edge_tts.Communicate(
            text=text,
            voice=req.voice,
            rate=req.rate,
            pitch=req.pitch,
        )

        # Collect all audio chunks
        audio_buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buf.write(chunk["data"])

        audio_buf.seek(0)
        audio_bytes = audio_buf.read()

        if not audio_bytes:
            raise HTTPException(500, "TTS produced no audio output.")

        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/mpeg",
            headers={
                "Content-Length": str(len(audio_bytes)),
                "Cache-Control": "no-cache",
            },
        )

    except edge_tts.exceptions.NoAudioReceived:
        logger.error("Edge-TTS: no audio received for voice=%s", req.voice)
        raise HTTPException(
            422,
            f"Voice '{req.voice}' produced no audio. "
            "Try 'en-US-AriaNeural' or check the voice name.",
        )
    except Exception as exc:
        logger.exception("TTS error: %s", exc)
        raise HTTPException(500, f"TTS error: {exc}")


# ── /stt  (Audio → transcript) ─────────────────────────────────────────────────

@app.post(
    "/stt",
    response_model=STTResponse,
    summary="Speech-to-text using faster-whisper",
)
async def speech_to_text(
    audio: UploadFile = File(..., description="WAV, WEBM, OGG, or MP3 file"),
    language: str = Form(default="en", description="BCP-47 language code hint, e.g. 'en'"),
):
    """
    Transcribe uploaded audio using Faster-Whisper running locally on CPU.
    The audio is written to a temp file, transcribed, then deleted.
    """
    if _whisper is None:
        raise HTTPException(503, "Whisper model not loaded yet.")

    # Validate content type loosely
    allowed_types = {
        "audio/wav", "audio/wave", "audio/x-wav",
        "audio/webm", "audio/ogg", "audio/mpeg",
        "audio/mp3", "video/webm",                 # Chrome records as video/webm
    }
    ct = (audio.content_type or "").lower()
    if ct and ct not in allowed_types:
        raise HTTPException(
            415,
            f"Unsupported audio type '{ct}'. "
            "Send WAV, WEBM, OGG, or MP3.",
        )

    raw = await audio.read()
    if len(raw) < 100:
        raise HTTPException(400, "Audio file is too small. Was the microphone captured?")

    # Write to a named temp file — Whisper needs a path, not bytes
    suffix = _ext_from_content_type(ct) or ".webm"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name

        loop = asyncio.get_event_loop()
        segments, info = await loop.run_in_executor(
            None,
            lambda: _whisper.transcribe(
                tmp_path,
                language=language if language else None,
                beam_size=5,
                vad_filter=True,          # skip silence
                vad_parameters={"min_silence_duration_ms": 300},
            ),
        )

        transcript = " ".join(seg.text.strip() for seg in segments).strip()
        detected_lang = getattr(info, "language", language)

    except Exception as exc:
        logger.exception("STT error: %s", exc)
        raise HTTPException(500, f"Transcription error: {exc}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    if not transcript:
        return STTResponse(transcript="", language=detected_lang, confidence=0.0)

    return STTResponse(
        transcript=transcript,
        language=detected_lang,
        confidence=None,   # faster-whisper does not expose segment-level confidence easily
    )


def _ext_from_content_type(ct: str) -> str:
    mapping = {
        "audio/wav":    ".wav",
        "audio/wave":   ".wav",
        "audio/x-wav":  ".wav",
        "audio/webm":   ".webm",
        "video/webm":   ".webm",
        "audio/ogg":    ".ogg",
        "audio/mpeg":   ".mp3",
        "audio/mp3":    ".mp3",
    }
    return mapping.get(ct, ".webm")


# ── /health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status":           "ok",
        "graph_ready":      graph is not None,
        "whisper_ready":    _whisper is not None,
        "whisper_model":    _WHISPER_MODEL_SIZE,
        "pending_sessions": len(_pending_sessions),
    }