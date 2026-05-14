import asyncio
import json
import logging
import multiprocessing
import os
import sys
import traceback
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv()

# ── Startup assertions — crash immediately if any key is missing ──────────────
required_env_vars = [
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "PINECONE_API_KEY",
    "PINECONE_INDEX_NAME",
    "INTERNAL_API_SECRET",
]
for var in required_env_vars:
    if not os.getenv(var):
        raise RuntimeError(
            f"MISSING REQUIRED ENV VAR: {var}. Check alpha_engine/.env"
        )

from backend.graph import compiled_graph
from ingestion.api_ingest import ingest_router

app = FastAPI(title="Alpha Engine API")

# ── CORS — allow frontend origin (env-configured) plus both localhost variants ──
# 127.0.0.1 is needed because Next.js server-side fetch uses 127.0.0.1, not
# the hostname "localhost", even when they resolve to the same address.
VERCEL_ORIGIN = os.getenv("VERCEL_FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        VERCEL_ORIGIN,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


# ── 20MB upload size limit middleware ─────────────────────────────────────────
# NOTE: Content-Length is only checked when present. Next.js App Router's fetch
# does NOT set Content-Length for FormData bodies (chunked transfer encoding),
# so we must not return 411 when it is absent — only reject when it is present
# and exceeds the limit. FastAPI's UploadFile handles oversized streams natively.
class LimitUploadSizeMiddleware(BaseHTTPMiddleware):
    MAX_BYTES = 20 * 1024 * 1024  # 20MB

    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and "/ingest" in request.url.path:
            cl = request.headers.get("content-length")
            if cl and int(cl) > self.MAX_BYTES:
                return Response(status_code=413, content="File exceeds 20MB limit.")
        return await call_next(request)


app.add_middleware(LimitUploadSizeMiddleware)

# Phase 7: PDF ingestion route — served from ingestion/ package
app.include_router(ingest_router, prefix="/api")

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


async def event_generator(user_query: str, thread_id: str, request: Request):
    """
    SSE generator — streams the full lifecycle of an Alpha Engine query.
    Event types: agent_status, agent_action, agent_token, alpha_signal, done.
    Halts immediately when client disconnects to conserve API credits.
    """
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 50,
    }
    initial_state = {
        "messages": [("user", user_query)],
        "current_agent": None,
        "signal_confidence": 0.0,
        "final_signal": None,
    }

    last_status_node = None

    try:
        async for event in compiled_graph.astream_events(
            initial_state, config=config, version="v2"
        ):
            # Halt immediately when client disconnects — saves API credits
            if await request.is_disconnected():
                logging.info("[analyze] Client disconnected. Halting LangGraph.")
                break

            event_type = event.get("event", "")
            name = event.get("name", "")
            metadata = event.get("metadata", {})
            lg_node = metadata.get("langgraph_node", "")

            # ── Node status events (shell-like feel) ──────────────────────────
            if lg_node in KNOWN_NODES and lg_node != last_status_node:
                last_status_node = lg_node
                yield (
                    f"event: agent_status\n"
                    f"data: {json.dumps({'node': lg_node, 'status': 'started', 'message': NODE_STATUS_MSG.get(lg_node, '')})}\n\n"
                )

            # ── Tool dispatch ─────────────────────────────────────────────────
            if event_type == "on_tool_start":
                tool_input = event.get("data", {}).get("input")
                yield (
                    f"event: agent_action\n"
                    f"data: {json.dumps({'type': 'tool_start', 'tool': name, 'input': tool_input})}\n\n"
                )

            # ── Tool result ───────────────────────────────────────────────────
            elif event_type == "on_tool_end":
                tool_output = event.get("data", {}).get("output", "")
                preview = str(tool_output)[:200]
                yield (
                    f"event: agent_action\n"
                    f"data: {json.dumps({'type': 'tool_end', 'tool': name, 'output_preview': preview})}\n\n"
                )

            # ── Synthesis tokens (streaming) ──────────────────────────────────
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

            # ── Alpha signal (structured output) ──────────────────────────────
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

    except asyncio.CancelledError:
        logging.warning("[analyze] StreamingResponse cancelled by ASGI server.")
    except GraphRecursionError:
        logging.error("[SSE] GraphRecursionError — gatekeeper failed to terminate.")
        payload = json.dumps({"type": "error", "content": "Agent hit recursion limit."})
        yield f"event: agent_error\ndata: {payload}\n\n"
    except Exception as e:
        logging.error(f"[SSE] Exception: {e}")
        traceback.print_exc(file=sys.stderr)
        payload = json.dumps({"type": "error", "content": str(e)})
        yield f"event: agent_error\ndata: {payload}\n\n"
    finally:
        yield "event: done\ndata: {}\n\n"


@app.post("/api/analyze")
async def analyze(request: QueryRequest, raw_request: Request):
    session_id = request.session_id or str(uuid.uuid4())
    return StreamingResponse(
        event_generator(request.query, session_id, raw_request),
        media_type="text/event-stream",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Windows-safe programmatic uvicorn entry point ─────────────────────────────
if __name__ == "__main__":
    import uvicorn

    # Required for Windows executable multiprocessing safety
    multiprocessing.freeze_support()

    # Cap at 2 workers for Windows spawn overhead (not fork)
    cpu_count = multiprocessing.cpu_count()
    safe_workers = min((cpu_count * 2) + 1, 2)

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        workers=safe_workers,
        # DO NOT add loop="uvloop" — crashes on Windows
        log_level="info",
        access_log=True,
        reload=False,  # Never use reload with workers > 1
    )
