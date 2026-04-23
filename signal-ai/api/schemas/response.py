from pydantic import BaseModel
from typing import Optional, List

class NewsPreviewItem(BaseModel):
    title: str
    source: str = ""
    summary: str = ""
    url: str = ""

class QueryResponse(BaseModel):
    response: str
    awaiting_confirmation: bool = False
    session_id: Optional[str] = None
    news_preview: Optional[List[NewsPreviewItem]] = None
    formatted_content: Optional[str] = None

class ConfirmResponse(BaseModel):
    response: str
    success: bool = True

class ChatResponse(BaseModel):
    response: str
    action: Optional[str] = None
    voice_text: Optional[str] = None

class STTResponse(BaseModel):
    transcript: str
    confidence: Optional[float] = None
    language: Optional[str] = None