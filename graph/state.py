"""Graph State — SwarmState TypedDict and request/response Pydantic models.
v2.0: Extended with execution_plan and current_step for LangGraph multi-agent flows."""
from typing import List, Optional, Annotated, TypedDict, Dict, Any
from pydantic import BaseModel, field_validator
from langchain_core.messages import BaseMessage


class SwarmState(TypedDict):
    """State that flows through the LangGraph StateGraph.
    
    v2.0 additions:
    - execution_plan: ordered list of agent IDs to execute sequentially
    - current_step: index into execution_plan (0-based)
    - model_name: LLM model to use for agent nodes
    - tenant_id: tenant isolation key
    - user_metadata: user profile for personalization
    - router_reasoning: explanation from the LLM router
    - router_confidence: 0.0-1.0 confidence from router
    """
    messages: Annotated[List[BaseMessage], "The messages in the conversation"]
    active_agent: str
    context: str
    agent_outputs: Dict[str, Any]
    # v2.0 — LangGraph multi-agent
    execution_plan: List[str]
    current_step: int
    model_name: str
    tenant_id: str
    user_metadata: Optional[Dict[str, Any]]
    router_reasoning: str
    router_confidence: float


class ChatMessage(BaseModel):
    role: str
    content: str
    agent_id: Optional[str] = None  # Track which agent authored this message

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("user", "assistant", "system"):
            raise ValueError("role must be 'user', 'assistant', or 'system'")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if len(v) > 10_000:
            raise ValueError("message content must be under 10,000 characters")
        return v


class Attachment(BaseModel):
    id: str
    name: str
    type: str
    size: int
    content: str  # base64 encoded


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    context: Optional[str] = None
    preferred_agent: Optional[str] = None
    model: Optional[str] = "Claude 3.5 Sonnet"
    tenant_id: str = "shift"
    session_id: Optional[str] = None
    search_enabled: Optional[bool] = False
    attachments: Optional[List[Attachment]] = []
    user_metadata: Optional[dict] = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: list) -> list:
        if len(v) > 50:
            raise ValueError("maximum 50 messages per request")
        if len(v) == 0:
            raise ValueError("at least one message is required")
        return v


class DebateDashboardRequest(BaseModel):
    topic: str
    expected_output: str
    agent_a_id: str
    agent_b_id: str
    soul_a: Optional[str] = ""
    soul_b: Optional[str] = ""
    turns: int = 1
    model: Optional[str] = "Claude Opus 4.6"
    tenant_id: str = "shift"
    session_id: Optional[str] = None
