import json
import sys
import uuid
import traceback
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langgraph.errors import GraphRecursionError

from graph import compiled_graph

app = FastAPI(title="Alpha Engine API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

KNOWN_NODES = {"supervisor", "quant", "fund", "synthesizer"}

NODE_STATUS_MSG = {
    "supervisor": "Supervisor analyzing query... routing to next agent.",
    "quant":      "Quant Agent computing volatility & momentum metrics...",
    "fund":       "Fund Agent retrieving SEC 10-K risk context from Pinecone...",
    "synthesizer":"Synthesizer generating structured AlphaSignal...",
}


class QueryRequest(BaseModel):
    query: str
    session_id: str = None


async def event_generator(request: QueryRequest):
    """
    SSE generator — streams the full lifecycle of an Alpha Engine query.
    Event types: agent_status, agent_action, agent_token, alpha_signal, done.
    """
    session_id = request.session_id or str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": 25,
    }
    initial_state = {
        "messages": [("user", request.query)],
        "current_agent": None,
        "signal_confidence": 0.0,
        "final_signal": None,
    }

    # Track which nodes we've emitted status for (reset on re-entry)
    last_status_node = None

    try:
        async for event in compiled_graph.astream_events(
            initial_state, config=config, version="v2"
        ):
            event_type = event.get("event", "")
            name = event.get("name", "")
            metadata = event.get("metadata", {})
            lg_node = metadata.get("langgraph_node", "")

            # ── Node status events (shell-like feel) ──────────────────────
            if lg_node in KNOWN_NODES and lg_node != last_status_node:
                last_status_node = lg_node
                yield (
                    f"event: agent_status\n"
                    f"data: {json.dumps({'node': lg_node, 'status': 'started', 'message': NODE_STATUS_MSG.get(lg_node, '')})}\n\n"
                )

            # ── Tool dispatch ─────────────────────────────────────────────
            if event_type == "on_tool_start":
                tool_input = event.get("data", {}).get("input")
                yield (
                    f"event: agent_action\n"
                    f"data: {json.dumps({'type': 'tool_start', 'tool': name, 'input': tool_input})}\n\n"
                )

            # ── Tool result ───────────────────────────────────────────────
            elif event_type == "on_tool_end":
                tool_output = event.get("data", {}).get("output", "")
                # Truncate long Pinecone results for the stream
                preview = str(tool_output)[:200]
                yield (
                    f"event: agent_action\n"
                    f"data: {json.dumps({'type': 'tool_end', 'tool': name, 'output_preview': preview})}\n\n"
                )

            # ── Synthesis tokens (streaming) ──────────────────────────────
            elif event_type == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk:
                    text = getattr(chunk, "content", None)
                    if not text:
                        tc_chunks = getattr(chunk, "tool_call_chunks", None)
                        if tc_chunks:
                            text = tc_chunks[0].get("args", "")
                    if text:
                        yield (
                            f"event: agent_token\n"
                            f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"
                        )

            # ── Alpha signal (structured output) ─────────────────────────
            elif event_type == "on_chain_end" and name == "synthesizer":
                output = event.get("data", {}).get("output", {})
                if isinstance(output, dict) and output.get("final_signal") is not None:
                    final_signal = output["final_signal"]
                    if hasattr(final_signal, "model_dump"):
                        signal_data = final_signal.model_dump()
                    elif isinstance(final_signal, dict):
                        signal_data = final_signal
                    else:
                        signal_data = dict(final_signal)
                    yield (
                        f"event: alpha_signal\n"
                        f"data: {json.dumps(signal_data)}\n\n"
                    )

    except GraphRecursionError:
        print("[SSE] GraphRecursionError — gatekeeper failed to terminate.", file=sys.stderr)
        yield f"event: error\ndata: {json.dumps({'detail': 'Recursion limit reached.'})}\n\n"
    except Exception as e:
        print(f"[SSE] Exception: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        yield f"event: error\ndata: {json.dumps({'detail': str(e)})}\n\n"
    finally:
        yield "event: done\ndata: {}\n\n"


@app.post("/api/analyze")
async def analyze(request: QueryRequest):
    return StreamingResponse(
        event_generator(request),
        media_type="text/event-stream",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
