import json
import logging
import os
import re
import traceback

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import RetryPolicy
from pydantic import ValidationError

from backend.state import AgentState, AlphaSignal
from backend.llm import supervisor_llm
from backend.tools.quant_tool import python_repl
from backend.tools.fund_tool import pinecone_search

load_dotenv()

# ── Retry Policy — applied to every LLM-invoking node ────────────────────────
# Retries up to 5 times on any exception (covers Groq 429, network blips, etc.)
groq_retry = RetryPolicy(
    initial_interval=2.0,
    backoff_factor=2.0,
    max_interval=20.0,
    max_attempts=5,
    retry_on=[Exception],
)

# ── Tool Registry — single source of truth for Groq validation ───────────────
# CRITICAL: This set must exactly match the function names decorated with @tool.
# Any name outside this set is a hallucination and will be sanitized before
# it ever reaches Groq's strict tool-call validator.
VALID_TOOLS = {"python_repl", "pinecone_search"}

# ── Tool Binding ──────────────────────────────────────────────────────────────
tools = [python_repl, pinecone_search]
supervisor_with_tools = supervisor_llm.bind_tools(tools)

# ── Supervisor System Prompt ──────────────────────────────────────────────────
# IMPORTANT: Explicitly name both tools and forbid everything else.
# Groq (llama-3.1-8b-instant) will hallucinate 'brave_search' when the user
# asks for "live data" — the prompt below pre-empts this by mapping that intent
# to python_repl (Yahoo Finance) and declaring web-search tools DO NOT EXIST.
SUPERVISOR_SYSTEM = """You are the routing Supervisor of a financial analysis pipeline.
You have access to EXACTLY TWO tools. No other tools exist:
  1. python_repl   — fetches live market data (price, volatility, momentum) via Yahoo Finance.
  2. pinecone_search — retrieves SEC filing / fundamental risk context from a vector database.

DO NOT attempt to call any other tool (e.g. brave_search, web_search, search, tavily_search).
There is NO web-search tool. For any request involving "live data", "live stock data",
or "current price", you MUST use python_repl — it already fetches real-time market data.

MANDATORY SEQUENCE (follow this based on how many ToolMessages are already in history):
  Step 1 — 0 ToolMessages: Call `python_repl` with the ticker and lookback_days=252.
  Step 2 — 1 ToolMessage:  Call `pinecone_search` with a risk-related query, the ticker, and the fiscal_year.
  Step 3 — 2+ ToolMessages: Do NOT call any tool. Respond with text only: "Analysis complete."

Skipping a step or calling an unlisted tool is FORBIDDEN.
"""


# ── Memory Trim Node — enforces token ceiling before supervisor sees state ─────
def memory_trim_node(state: AgentState) -> dict:
    """
    The truncate_messages reducer in state.py already caps the merged history.
    This node is now a pass-through; the reducer handles trimming on every delta.
    Kept for graph topology stability.
    """
    return {}


# ── Pre-flight Tool-Call Sanitizer ───────────────────────────────────────────
def _sanitize_tool_calls(response: AIMessage, tool_count: int) -> AIMessage:
    """
    Intercepts hallucinated tool names BEFORE they are appended to state.

    Groq's strict validator crashes with:
      'tool call validation failed: attempted to call tool X which was not in request.tools'
    if the LLM emits a tool name not in VALID_TOOLS (e.g. 'brave_search' when the
    user asks for 'live data').

    Strategy:
      - Keep only tool_calls whose name is in VALID_TOOLS.
      - If nothing valid remains, inject the contextually correct forced call:
          tool_count == 0  →  python_repl  (quantitative step)
          tool_count == 1  →  pinecone_search  (fundamental step)
      - Always strip down to a SINGLE tool_call to enforce sequential execution.
    """
    tool_calls = getattr(response, "tool_calls", []) or []

    # Filter to only known-good tool names
    valid_calls = [tc for tc in tool_calls if tc.get("name") in VALID_TOOLS]

    # If the LLM produced nothing valid, log and substitute the correct step
    if not valid_calls:
        bad_names = [tc.get("name") for tc in tool_calls]
        if bad_names:
            logging.warning(
                f"[supervisor] Hallucinated tool call(s) detected and stripped: {bad_names}. "
                f"Substituting correct tool for step {tool_count + 1}."
            )
        if tool_count == 0:
            # Force python_repl — extract ticker from content if possible
            forced_call = {
                "name": "python_repl",
                "args": {"ticker": "UNKNOWN", "lookback_days": 252},
                "id": f"forced_quant_{tool_count}",
                "type": "tool_call",
            }
        else:
            # Force pinecone_search
            forced_call = {
                "name": "pinecone_search",
                "args": {"query": "risk factors", "ticker": "UNKNOWN", "fiscal_year": 2024},
                "id": f"forced_fund_{tool_count}",
                "type": "tool_call",
            }
        valid_calls = [forced_call]

    # Enforce single tool_call (no parallel dispatch to Groq)
    valid_calls = [valid_calls[0]]

    response.tool_calls = valid_calls
    # Keep additional_kwargs in sync so Groq's wire format stays consistent
    if hasattr(response, "additional_kwargs") and "tool_calls" in response.additional_kwargs:
        response.additional_kwargs["tool_calls"] = valid_calls

    return response


# ── Supervisor Node ───────────────────────────────────────────────────────────
def supervisor_node(state: AgentState) -> dict:
    """
    Deterministic multi-tool sequencer.
    Counts completed ToolMessages to decide the next step:
      0 tools done → call LLM, sanitize, force python_repl (quant)
      1 tool done  → call LLM, sanitize, force pinecone_search (fund)
      2+ tools done → skip LLM entirely, route straight to synthesizer

    The _sanitize_tool_calls() pre-flight check runs on EVERY LLM response
    before it is appended to state, ensuring Groq never sees a history that
    contains a hallucinated tool name (e.g. 'brave_search').
    """
    messages = state["messages"]
    tool_count = sum(1 for m in messages if isinstance(m, ToolMessage))

    # Step 3: Both tools done — bypass LLM entirely
    if tool_count >= 2:
        done_msg = AIMessage(
            content="Analysis complete. Both quantitative and fundamental data collected."
        )
        return {"current_agent": "synthesizer", "messages": [done_msg]}

    llm_messages = [SystemMessage(content=SUPERVISOR_SYSTEM)] + messages
    response = supervisor_with_tools.invoke(llm_messages)

    # ── PRE-FLIGHT: sanitize before touching state ────────────────────────────
    tool_calls = getattr(response, "tool_calls", []) or []

    if tool_calls:
        # LLM produced tool_calls — sanitize and route
        response = _sanitize_tool_calls(response, tool_count)
        tool_calls = response.tool_calls
        next_agent = "quant" if tool_calls[0]["name"] == "python_repl" else "fund"
    else:
        # LLM produced NO tool_calls (returned plain text instead)
        # Inject a forced call for the current step rather than a second LLM round-trip
        logging.warning(
            f"[supervisor] LLM returned no tool_calls at step {tool_count + 1}. "
            f"Injecting forced call."
        )
        response = _sanitize_tool_calls(response, tool_count)
        tool_calls = response.tool_calls
        next_agent = "quant" if tool_calls[0]["name"] == "python_repl" else "fund"

    return {"current_agent": next_agent, "messages": [response]}


# ── Tool Error Handlers — guarantee [QUANT]/[FUND] tags even on failure ───────
def _handle_quant_error(error: Exception) -> str:
    """Ensures [QUANT] tag is always present, even on tool failure."""
    logging.error(f"[quant_node] Tool error: {error}")
    return f"[QUANT] Tool execution failed: {str(error)[:200]}. Proceed with available data."


def _handle_fund_error(error: Exception) -> str:
    """Ensures [FUND] tag is always present, even on tool failure."""
    logging.error(f"[fund_node] Tool error: {error}")
    return f"[FUND] Tool execution failed: {str(error)[:200]}. Proceed with available data."


# ── Tool Executor Nodes (ToolNode with error handlers) ────────────────────────
quant_node = ToolNode([python_repl], handle_tool_errors=_handle_quant_error)
fund_node = ToolNode([pinecone_search], handle_tool_errors=_handle_fund_error)


# ── Synthesizer Helpers ───────────────────────────────────────────────────────
SYNTH_SYSTEM = """You are a Senior Hedge Fund Quantitative Analyst.
Your objective is to synthesize raw execution history into a definitive, structured AlphaSignal.

You MUST respond with ONLY a valid JSON object — no markdown fences, no preamble, no explanation.

The JSON must have exactly these 6 fields:
{
  "ticker": "<string: ticker symbol>",
  "direction": "<string: exactly one of Bullish, Bearish, Neutral>",
  "volatility": <float: annualized volatility from quant data, e.g. 0.4532>,
  "momentum": <float: 90-day momentum from quant data, e.g. 0.0712>,
  "risk_summary": "<string: 2-sentence risk summary>",
  "confidence": <float: strict value between 0.0 and 1.0>
}

Rules for synthesis:
1. EXTRACT: Pull the exact 'volatility' and 'momentum' floats from the [QUANT] tool output.
2. ANALYZE: Review the [FUND] fundamental SEC text chunks for macroeconomic headwinds.
3. DIRECTION: Classify as Bullish, Bearish, or Neutral. High volatility + negative risk = Bearish or Neutral.
4. CONFIDENCE: High (>0.8) = strong alignment between quant and fundamental. Low (<0.4) = conflicting signals.
5. SUMMARY: 2-sentence risk_summary justifying direction and confidence.
"""


def _parse_alpha_signal(raw_content: str) -> AlphaSignal:
    """
    Robustly extracts AlphaSignal from LLM output that may contain
    markdown fences, preamble text, or hallucinated formatting.
    """
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?", "", raw_content).strip()
    # Remove trailing ``` if any
    text = re.sub(r"```\s*$", "", text).strip()
    # Extract the first complete {...} JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(
            f"No JSON object found in synthesizer output: {text[:300]}"
        )
    data = json.loads(match.group(0))
    return AlphaSignal(**data)


def synthesizer_node(state: AgentState) -> dict:
    """
    Uses Groq llama-3.1-8b-instant with JSON mode forced via system prompt.
    Falls back to a safe default AlphaSignal on any parse failure.
    Does NOT use with_structured_output — unreliable for strict float extraction.
    """
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0,
        google_api_key=os.getenv("GEMINI_API_KEY"),
    )
    # Force JSON output via generation config
    llm_json = llm.bind(generation_config={"response_mime_type": "application/json"})

    messages = [SystemMessage(content=SYNTH_SYSTEM)] + state["messages"]

    try:
        response = llm_json.invoke(messages)
        signal = _parse_alpha_signal(response.content)
    except (ValidationError, json.JSONDecodeError, ValueError) as e:
        logging.error(f"[synthesizer] Parse failed: {e}")
        # Safe fallback — never crash the graph
        signal = AlphaSignal(
            ticker="UNKNOWN",
            direction="Neutral",
            volatility=0.0,
            momentum=0.0,
            risk_summary=f"Synthesis parsing failed: {str(e)[:300]}",
            confidence=0.0,
        )
        response = AIMessage(content=str(signal.model_dump()))
    except Exception as e:
        logging.error(f"[synthesizer] LLM call failed: {e}")
        traceback.print_exc()
        signal = AlphaSignal(
            ticker="UNKNOWN",
            direction="Neutral",
            volatility=0.0,
            momentum=0.0,
            risk_summary=f"Synthesizer LLM failed: {str(e)[:300]}",
            confidence=0.0,
        )
        response = AIMessage(content=str(signal.model_dump()))

    return {"final_signal": signal, "signal_confidence": signal.confidence, "messages": [response]}


# ── Gatekeeper Router ─────────────────────────────────────────────────────────
def supervisor_router(state: AgentState) -> str:
    """
    GATEKEEPER: Respects the supervisor's routing decision BUT overrides
    to 'synthesizer' if:
      1. Two or more ToolMessages exist (both tools have completed), OR
      2. The supervisor has looped 4+ times (safety cap), OR
      3. Both [QUANT] and [FUND] tags appear in message content (string check).
    """
    messages = state["messages"]

    tool_results = sum(1 for m in messages if isinstance(m, ToolMessage))
    supervisor_calls = sum(1 for m in messages if isinstance(m, AIMessage))

    # Primary gatekeeper: ToolMessage count
    if tool_results >= 2 or supervisor_calls >= 4:
        return "synthesizer"

    # Secondary gatekeeper: content string check (catches ToolNode error handler output)
    has_quant = any(
        "[QUANT]" in (
            m.content if hasattr(m, "content") and isinstance(m.content, str) else str(m)
        )
        for m in messages
    )
    has_fund = any(
        "[FUND]" in (
            m.content if hasattr(m, "content") and isinstance(m.content, str) else str(m)
        )
        for m in messages
    )
    if has_quant and has_fund:
        return "synthesizer"

    return state.get("current_agent", "synthesizer")


# ── Graph Assembly (Hub-and-Spoke with Memory Trim) ───────────────────────────
builder = StateGraph(AgentState)

# memory_trim runs first — now a pass-through; trimming handled by state reducer
builder.add_node("memory_trim", memory_trim_node)

# All LLM nodes get RetryPolicy — handles Groq 429 mid-graph without crashing
builder.add_node("supervisor", supervisor_node, retry=groq_retry)
builder.add_node("quant", quant_node)
builder.add_node("fund", fund_node)
builder.add_node("synthesizer", synthesizer_node, retry=groq_retry)

# memory_trim is the entry point
builder.set_entry_point("memory_trim")
builder.add_edge("memory_trim", "supervisor")

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
