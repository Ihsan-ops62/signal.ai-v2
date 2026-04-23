from pydantic import BaseModel, Field
from typing import Optional

class QueryRequest(BaseModel):
    query: str

class ConfirmRequest(BaseModel):
    session_id: str
    confirmed: bool

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    voice_mode: bool = Field(default=False)

class TTSRequest(BaseModel):
    text: str
    voice: str = "en-US-AriaNeural"
    rate: str = "+0%"
    pitch: str = "+0Hz"