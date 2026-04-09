from pydantic import BaseModel, Field
from typing import Optional, List


# ── Existing schemas ───────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str


class NewsPreviewItem(BaseModel):
    title:   str
    source:  str = ""
    summary: str = ""


class QueryResponse(BaseModel):
    response:              str
    awaiting_confirmation: bool = False
    session_id:            Optional[str] = None
    news_preview:          Optional[List[NewsPreviewItem]] = None


class ConfirmRequest(BaseModel):
    session_id: str
    confirmed:  bool


class ConfirmResponse(BaseModel):
    response: str
    success:  bool = True


# ── Chat (text) ────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:    str
    session_id: Optional[str] = None
    voice_mode: bool = Field(
        default=False,
        description="When True the response is stripped of markdown for TTS readability.",
    )


class ChatResponse(BaseModel):
    response:   str
    action:     Optional[str] = None
    voice_text: Optional[str] = None   # same as response when voice_mode=True


# ── Text-to-Speech ─────────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text:  str = Field(..., description="The text to synthesise.")
    voice: str = Field(
        default="en-US-AriaNeural",
        description=(
            "Edge-TTS voice name. Examples: "
            "'en-US-AriaNeural' (female, warm), "
            "'en-US-GuyNeural' (male), "
            "'en-GB-SoniaNeural' (British female)."
        ),
    )
    rate:   str = Field(default="+0%",    description="Speech rate offset, e.g. '+10%' or '-5%'.")
    pitch:  str = Field(default="+0Hz",   description="Pitch offset, e.g. '+5Hz'.")


# ── Speech-to-Text ─────────────────────────────────────────────────────────────

class STTResponse(BaseModel):
    transcript: str
    confidence: Optional[float] = None   # 0.0-1.0 if the backend provides it
    language:   Optional[str]   = None   # detected language code, e.g. "en"