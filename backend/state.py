from typing import Annotated, Optional
from pydantic import BaseModel
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph.message import add_messages


class AlphaSignal(BaseModel):
    ticker:       str
    direction:    str          # "Bullish" | "Bearish" | "Neutral"
    volatility:   float
    momentum:     float
    risk_summary: str
    confidence:   float        # strict float 0.0–1.0


def truncate_messages(left: list, right: list) -> list:
    """
    Merges messages then caps history to prevent O(N²) token growth.
    Retains: all system messages + the 6 most recent non-system messages.
    Keeps ~3,000–4,000 tokens max per turn, staying within Groq's 6,000 TPM limit.
    """
    merged = add_messages(left, right)
    system_msgs = [m for m in merged if isinstance(m, SystemMessage)]
    non_system = [m for m in merged if not isinstance(m, SystemMessage)]
    # Keep only the 6 most recent non-system messages
    trimmed = non_system[-6:]
    return system_msgs + trimmed


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], truncate_messages]
    current_agent: Optional[str]
    signal_confidence: float
    final_signal: Optional[AlphaSignal]