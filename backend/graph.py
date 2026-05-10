import os
import traceback
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, ToolMessage, AIMessage
from langgraph.graph import StateGraph, END
from state import AgentState, AlphaSignal
from llm import supervisor_llm
from tools.quant_tool import python_repl
from tools.fund_tool import pinecone_search

load_dotenv()

# ── Tool Binding ──────────────────────────────────────────────────────────────
tools = [python_repl, pinecone_search]
supervisor_with_tools = supervisor_llm.bind_tools(tools)

# ── Supervisor System Prompt (multi-tool sequencing) ─────────────────────────
SUPERVISOR_SYSTEM = """You are the routing Supervisor of a financial analysis pipeline.
You MUST call exactly two tools, in this exact order, before stopping.

MANDATORY SEQUENCE:
Step 1: You MUST call `python_repl` first. Pass the ticker and lookback_days=252.
Step 2: After python_repl returns, you MUST call `pinecone_search`. Pass a risk-related query, the ticker, and the fiscal_year.
Step 3: After BOTH tools have returned, respond with text only. Do NOT call any tool.

STATE DETECTION:
- No ToolMessage in history => You are at Step 1. Call python_repl NOW.
- Exactly 1 ToolMessage in history => You are at Step 2. Call pinecone_search NOW.
- 2 or more ToolMessages in history => You are at Step 3. STOP. Say "Analysis complete."

You MUST follow this sequence. Skipping a step is FORBIDDEN.
"""


# ── Supervisor Node ──────────────────────────────────────────────────────────
def supervisor_node(state: AgentState) -> dict:
    """
    Deterministic multi-tool sequencer with LLM fallback.
    Counts completed ToolMessages to decide the next step:
      0 tools done → force python_repl (quant)
      1 tool done  → force pinecone_search (fund)
      2+ tools done → skip LLM, route to synthesizer

    CRITICAL: If the LLM emits multiple tool_calls in one response,
    we strip it down to only the FIRST one to force sequential execution.
    """
    messages = state["messages"]
    tool_count = sum(1 for m in messages if isinstance(m, ToolMessage))

    # Step 3: Both tools done — don't even call the LLM, just route out
    if tool_count >= 2:
        from langchain_core.messages import AIMessage as _AI
        done_msg = _AI(content="Analysis complete. Both quantitative and fundamental data collected.")
        return {"current_agent": "synthesizer", "messages": [done_msg]}

    # Steps 1 & 2: Call the LLM for a natural-sounding response
    llm_messages = [SystemMessage(content=SUPERVISOR_SYSTEM)] + messages
    response = supervisor_with_tools.invoke(llm_messages)

    tool_calls = getattr(response, "tool_calls", [])

    if tool_calls:
        # CRITICAL: Strip to single tool_call to force sequential dispatch.
        # If the LLM emitted both python_repl and pinecone_search at once,
        # only keep the first one. The orphaned second call would confuse the loop.
        if len(tool_calls) > 1:
            response.tool_calls = [tool_calls[0]]
            # Also fix additional_kwargs if present
            if hasattr(response, 'additional_kwargs') and 'tool_calls' in response.additional_kwargs:
                response.additional_kwargs['tool_calls'] = [response.additional_kwargs['tool_calls'][0]]

        next_agent = "quant" if tool_calls[0]["name"] == "python_repl" else "fund"
    elif tool_count == 0:
        # LLM failed to call python_repl — nudge it
        from langchain_core.messages import AIMessage as _AI
        response = supervisor_with_tools.invoke(
            llm_messages + [_AI(content="I need to call python_repl first.")]
        )
        tool_calls = getattr(response, "tool_calls", [])
        next_agent = "quant" if tool_calls else "synthesizer"
    elif tool_count == 1:
        # LLM failed to call pinecone_search — nudge it
        from langchain_core.messages import AIMessage as _AI
        response = supervisor_with_tools.invoke(
            llm_messages + [_AI(content="Now I must call pinecone_search.")]
        )
        tool_calls = getattr(response, "tool_calls", [])
        next_agent = "fund" if tool_calls else "synthesizer"
    else:
        next_agent = "synthesizer"

    return {"current_agent": next_agent, "messages": [response]}


# ── Tool Executor Nodes ──────────────────────────────────────────────────────
def quant_node(state: AgentState) -> dict:
    """Executes python_repl with the LLM-provided arguments."""
    last_msg = state["messages"][-1]
    tc = last_msg.tool_calls[0]
    result = python_repl.invoke(tc["args"])
    return {"messages": [ToolMessage(tool_call_id=tc["id"], content=str(result))]}


def fund_node(state: AgentState) -> dict:
    """Executes pinecone_search with the LLM-provided arguments."""
    last_msg = state["messages"][-1]
    tc = last_msg.tool_calls[0]
    try:
        result = pinecone_search.invoke(tc["args"])
    except Exception as e:
        print(f"[fund_node] Pinecone search failed: {e}")
        traceback.print_exc()
        result = f"[FUND] Pinecone search error: {e}"
    return {"messages": [ToolMessage(tool_call_id=tc["id"], content=str(result))]}


# ── Synthesizer Node ─────────────────────────────────────────────────────────
SYNTH_SYSTEM = """You are a Senior Hedge Fund Quantitative Analyst.
Your objective is to synthesize raw execution history into a definitive, structured AlphaSignal.

Rules for synthesis:
1. EXTRACT: Pull the exact 'ticker', 'volatility', and 'momentum' floats from the quant tool output.
2. ANALYZE: Review the fundamental SEC text chunks for macroeconomic headwinds or supply chain risks.
3. DIRECTION: Classify as 'Bullish', 'Bearish', or 'Neutral'. If momentum is positive but fundamental risk is severe, downgrade to Neutral or Bearish.
4. CONFIDENCE: Calculate a strict float between 0.0 and 1.0. Do NOT default to 0.5.
   - High Confidence (>0.8): Strong alignment between quantitative momentum and qualitative SEC outlook.
   - Low Confidence (<0.4): Conflicting signals (e.g., high volatility, negative SEC risk factors, positive momentum).
5. SUMMARY: Provide a dense, 2-sentence 'risk_summary' justifying the direction and confidence.
"""


def synthesizer_node(state: AgentState) -> dict:
    """Uses Groq with structured output to produce the final AlphaSignal."""
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0,
        api_key=os.getenv("GROQ_API_KEY"),
    )
    structured_llm = llm.with_structured_output(AlphaSignal)
    messages = [SystemMessage(content=SYNTH_SYSTEM)] + state["messages"]
    signal = structured_llm.invoke(messages)
    return {"final_signal": signal, "signal_confidence": signal.confidence}


# ── Gatekeeper Router ─────────────────────────────────────────────────────────
def supervisor_router(state: AgentState) -> str:
    """
    GATEKEEPER: Respects the supervisor's routing decision BUT overrides
    to 'synthesizer' if:
      1. Two or more ToolMessages exist (both tools have completed), OR
      2. The supervisor has looped 4+ times (safety cap).
    """
    messages = state["messages"]

    tool_results = sum(1 for m in messages if isinstance(m, ToolMessage))
    supervisor_calls = sum(1 for m in messages if isinstance(m, AIMessage))

    if tool_results >= 2 or supervisor_calls >= 4:
        return "synthesizer"

    return state.get("current_agent", "synthesizer")


# ── Graph Assembly (Hub-and-Spoke) ────────────────────────────────────────────
builder = StateGraph(AgentState)

builder.add_node("supervisor", supervisor_node)
builder.add_node("quant", quant_node)
builder.add_node("fund", fund_node)
builder.add_node("synthesizer", synthesizer_node)

builder.set_entry_point("supervisor")

# Supervisor dispatches to tool nodes or synthesizer
builder.add_conditional_edges(
    "supervisor",
    supervisor_router,
    {"quant": "quant", "fund": "fund", "synthesizer": "synthesizer"},
)

# Hub-and-Spoke: Tool nodes loop BACK to supervisor for re-evaluation
builder.add_edge("quant", "supervisor")
builder.add_edge("fund", "supervisor")

# Synthesizer is terminal
builder.add_edge("synthesizer", END)

compiled_graph = builder.compile()
