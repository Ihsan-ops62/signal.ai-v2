from pydantic import BaseModel, Field
from typing import Optional, List


class QueryRequest(BaseModel):
    query: str


class NewsPreviewItem(BaseModel):
    title:   str
    source:  str = ""
    summary: str = ""
    url:     str = ""


class QueryResponse(BaseModel):
    response:              str
    awaiting_confirmation: bool = False
    session_id:            Optional[str] = None
    news_preview:          Optional[List[NewsPreviewItem]] = None
    formatted_content:     Optional[str] = None  # The drafted LinkedIn post


class ConfirmRequest(BaseModel):
    session_id: str
    confirmed:  bool


class ConfirmResponse(BaseModel):
    response: str
    success:  bool = True


class ChatRequest(BaseModel):
    message:    str
    session_id: Optional[str] = None
    voice_mode: bool = Field(default=False)


class ChatResponse(BaseModel):
    response:   str
    action:     Optional[str] = None
    voice_text: Optional[str] = None


class TTSRequest(BaseModel):
    text:  str
    voice: str = "en-US-AriaNeural"
    rate:  str = "+0%"
    pitch: str = "+0Hz"


class STTResponse(BaseModel):
    transcript: str
    confidence: Optional[float] = None
    language:   Optional[str]   = None