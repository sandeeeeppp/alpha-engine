from typing import Annotated, Optional
from pydantic import BaseModel
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages

class AlphaSignal(BaseModel):
    ticker:       str
    direction:    str          # "Bullish" | "Bearish" | "Neutral"
    volatility:   float
    momentum:     float
    risk_summary: str
    confidence:   float        # <--- Make sure this line exists and is spelled correctly!

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    current_agent: Optional[str]
    signal_confidence: float
    final_signal: Optional[AlphaSignal]