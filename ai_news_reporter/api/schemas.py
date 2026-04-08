from pydantic import BaseModel
from typing import Optional, List


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    response: str
    awaiting_confirmation: bool = False
    session_id: Optional[str] = None
    news_preview: Optional[List[dict]] = None


class ConfirmRequest(BaseModel):
    session_id: str
    confirmed: bool


class ConfirmResponse(BaseModel):
    response: str
    success: bool = True