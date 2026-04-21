
from typing import TypedDict, Optional, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class NewsArticle:
    """News article data."""
    id: str
    title: str
    description: str
    content: str
    url: str
    source: str
    published_at: datetime
    author: Optional[str]
    image_url: Optional[str]
    summary: Optional[str] = None
    quality_score: float = 0.0


@dataclass
class SocialPost:
    """Social media post data."""
    id: str
    content: str
    platform: str
    media_urls: Optional[List[str]] = None
    scheduled_time: Optional[datetime] = None


@dataclass
class WorkflowMessage:
    """Message in workflow conversation."""
    role: str  # "user", "assistant"
    content: str
    timestamp: datetime


class AgentState(TypedDict):
    """
    State dictionary passed through LangGraph workflow.
    Represents the complete context for agent processing.
    """
    # Input query/request
    query: str
    user_id: str
    conversation_id: Optional[str]
    
    # Intent classification
    intent: Optional[str]  # "search_news", "summarize", "post", "discuss"
    confidence: float  # 0.0-1.0
    
    # News search results
    articles: List[NewsArticle]
    search_query: Optional[str]
    
    # Processing pipeline
    selected_articles: List[NewsArticle]
    summaries: dict[str, str]  # article_id -> summary
    formatted_posts: dict[str, SocialPost]  # platform -> post
    
    # Conversation context
    messages: List[WorkflowMessage]
    conversation_history: List[dict]  # Full conversation
    
    # Execution metadata
    workflow_stage: str  # "init", "intent", "search", "process", "post", "complete"
    errors: List[str]
    metadata: dict  # Additional context
    
    # Output
    response: Optional[str]
    posts_created: List[SocialPost]
    
    # Timestamp tracking
    created_at: datetime
    updated_at: datetime


class IntentClassificationResult(TypedDict):
    """Result of intent classification."""
    intent: str
    confidence: float
    parameters: dict


class SearchResult(TypedDict):
    """Result of news search."""
    articles: List[NewsArticle]
    total: int
    search_query: str


class SummarizationResult(TypedDict):
    """Result of content summarization."""
    article_id: str
    summary: str
    key_points: List[str]


class FormattingResult(TypedDict):
    """Result of platform-specific formatting."""
    platform: str
    content: str
    media_urls: Optional[List[str]]


# Helper functions for state management


def create_initial_state(
    query: str,
    user_id: str,
    conversation_id: Optional[str] = None
) -> AgentState:
    """Create initial workflow state."""
    now = datetime.utcnow()
    return AgentState(
        query=query,
        user_id=user_id,
        conversation_id=conversation_id,
        intent=None,
        confidence=0.0,
        articles=[],
        search_query=None,
        selected_articles=[],
        summaries={},
        formatted_posts={},
        messages=[],
        conversation_history=[],
        workflow_stage="init",
        errors=[],
        metadata={},
        response=None,
        posts_created=[],
        created_at=now,
        updated_at=now
    )


def add_error(state: AgentState, error: str) -> AgentState:
    """Add error to state."""
    state["errors"].append(error)
    state["updated_at"] = datetime.utcnow()
    return state


def update_stage(state: AgentState, stage: str) -> AgentState:
    """Update workflow stage."""
    state["workflow_stage"] = stage
    state["updated_at"] = datetime.utcnow()
    return state


def add_message(
    state: AgentState,
    role: str,
    content: str
) -> AgentState:
    """Add message to conversation."""
    msg = WorkflowMessage(
        role=role,
        content=content,
        timestamp=datetime.utcnow()
    )
    state["messages"].append(msg)
    state["conversation_history"].append({
        "role": role,
        "content": content,
        "timestamp": msg.timestamp.isoformat()
    })
    state["updated_at"] = datetime.utcnow()
    return state
