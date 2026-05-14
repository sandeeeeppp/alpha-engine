# Alpha Engine ⚡

> A production-grade Agentic RAG pipeline for real-time financial analysis.

Alpha Engine combines a **LangGraph multi-agent orchestrator** with **Pinecone vector search** and **live market data** to generate structured `AlphaSignal` outputs — a hedge fund analyst, delivered as an API.

---

## Features

| Capability | Detail |
|---|---|
| **Multi-Agent Orchestration** | Deterministic Supervisor → Quant → Fund → Synthesizer pipeline |
| **Live Market Data** | Yahoo Finance via `python_repl` tool (price, volatility, 90d momentum) |
| **SEC Filing Retrieval** | Pinecone vector search over ingested 8-K/10-K PDFs (`pinecone_search` tool) |
| **Real-Time PDF Ingestion** | FastAPI endpoint with per-job status tracking and SSE progress streaming |
| **Structured Output** | Pydantic `AlphaSignal` schema: ticker, direction, volatility, momentum, confidence |
| **SSE Streaming** | Server-Sent Events pipeline — shell-like agent terminal experience in the frontend |
| **Groq Strict Mode Compatible** | Pre-flight tool-call sanitizer intercepts hallucinated tool names before Groq's validator |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend API** | FastAPI + Uvicorn |
| **Agent Orchestration** | LangGraph (StateGraph, ToolNode, RetryPolicy) |
| **Supervisor LLM** | Groq — `llama-3.1-8b-instant` |
| **Synthesizer LLM** | Google Gemini — `gemini-2.5-flash` |
| **Embeddings** | Google Gemini — `models/text-embedding-004` |
| **Vector Store** | Pinecone (serverless) |
| **Market Data** | yfinance (Yahoo Finance) |
| **Frontend** | Next.js 14+ (App Router) |

---

## Architectural Philosophy

### v1.0 — Deterministic DAG (Current)

Alpha Engine v1.0 is deliberately implemented as a **Deterministic Directed Acyclic Graph (DAG)**. The pipeline enforces a fixed, mandatory sequence:

```
memory_trim → supervisor → quant → supervisor → fund → supervisor → synthesizer
```

The Supervisor node does not use LLM judgment to decide which tool to call next. Instead, it counts the number of `ToolMessage` objects already present in state and maps that count to a forced action:

| ToolMessages in State | Supervisor Action |
|---|---|
| 0 | Force-call `python_repl` (Quant) |
| 1 | Force-call `pinecone_search` (Fund) |
| ≥ 2 | Bypass LLM entirely — route directly to Synthesizer |

**Why a DAG instead of a free-form agent loop?**

This is a deliberate production guardrail, not a limitation. `llama-3.1-8b-instant` on Groq exhibits two failure modes in unconstrained agentic loops:

1. **Ghost Tool Hallucination:** When given a vague query involving "live data," the model occasionally emits a `brave_search` tool call — a name it learned from training data but that is not registered in the schema. Groq's strict tool-call validator kills the connection immediately with a hard `APIError`. The DAG prevents this by never giving the LLM the freedom to invent its own tool sequence.

2. **Infinite Loop Risk:** Small models under instruction-following pressure can enter cycles (e.g., re-calling a tool after receiving its result). The DAG's `ToolMessage` counter and a hard gatekeeper cap (`supervisor_calls >= 4`) make infinite loops structurally impossible.

A **pre-flight sanitizer** (`_sanitize_tool_calls()` in `graph.py`) provides a second layer of defence: it intercepts any LLM response containing an unrecognised tool name and substitutes the contextually correct forced call before the response ever touches application state.

---

## Agent Pipeline

```
                        User Query
                            │
                            ▼
                      [memory_trim]
                            │
                            ▼
                       [supervisor] ◄──────────────┐
                            │                      │
              ┌─────────────┴──────────────┐       │
              │  ToolMessage count = 0     │       │
              ▼                            │       │
           [quant]                         │       │
       (python_repl)                       │       │
       Yahoo Finance                       │       │
              │                            │       │
              └──────────────►  [supervisor]       │
                                    │              │
                         ┌──────────┴───────────┐  │
                         │ ToolMessage count = 1 │  │
                         ▼                      │  │
                      [fund]                    │  │
                 (pinecone_search)              │  │
                 Pinecone / SEC RAG             │  │
                         │                     │  │
                         └──────────►  [supervisor]
                                           │
                              ToolMessage count ≥ 2
                                           │
                                           ▼
                                    [synthesizer]
                                           │
                                           ▼
                                   AlphaSignal JSON
                         {ticker, direction, volatility,
                          momentum, risk_summary, confidence}
```

The Supervisor uses a **deterministic ToolMessage counter** — not LLM judgment — to gate each step. The `supervisor_router` gatekeeper additionally monitors `AIMessage` count and content tags (`[QUANT]`, `[FUND]`) as redundant termination signals.

---

## Roadmap: Transition to Cyclic Graph (v2.0)

The v2.0 architecture targets a true **Hub-and-Spoke cyclic graph** where the Supervisor retains the ability to re-query agents for self-correcting RAG — for example, re-running `pinecone_search` with a refined query if the first retrieval yields low-confidence chunks.

```
[memory_trim] → [supervisor] ⇄ [quant]
                     ⇅
                  [fund]
                     │
              (when satisfied)
                     ▼
              [synthesizer]
```

### Engineering Challenges Being Solved for v2.0

**1. The Ghost Tool Paradox**  
Allowing the Supervisor to make free-form routing decisions requires the LLM to reliably choose only from `{python_repl, pinecone_search}` across an unbounded number of turns. The current `_sanitize_tool_calls()` sanitizer already handles this defensively. For v2.0, the plan is to migrate the Supervisor to a model with better instruction-following fidelity (e.g., `llama-3.3-70b` or a Gemini model with native tool-use grounding) to make the sanitizer a safety net rather than a load-bearing component.

**2. Context Bloat**  
A cyclic graph accumulates `ToolMessage` history across multiple re-queries. Without active trimming, the Supervisor's context window fills rapidly, degrading routing quality and increasing Groq API latency. The current `memory_trim` node (a pass-through in v1.0) will be upgraded to an active LangChain `trim_messages()` call that preserves the most recent N tool results while discarding stale intermediate turns.

**3. Self-Correcting RAG Threshold**  
The Supervisor will need a confidence signal to decide whether to re-query or proceed. The plan is to expose Pinecone's match scores through `pinecone_search` output and have the Supervisor evaluate whether `max_score < 0.85` warrants a refined retrieval pass.

---

## Known Issues (v1.0 Technical Debt)

### 🐻 The Bear Trap — Malformed JSON on Complex Bearish Queries

**Affected component:** `synthesizer_node` → `_parse_alpha_signal()`  
**Trigger:** Queries that combine multiple simultaneous bearish signals (e.g., *"TSLA — Death Cross confirmed, margin compression accelerating, flag SEC-disclosed operational risks"*).  
**Error:**
```
Synthesis parsing failed: Expecting property name enclosed in double quotes:
line 3 column 1 (char 22)
```

**Root Cause:** When the synthesizer's `risk_summary` field must express multi-factor bearish reasoning, the response token count rises significantly. At these lengths, `llama-3.1-8b-instant` occasionally reverts to single-quoted strings, omits a closing brace, or embeds markdown syntax inside the JSON string — producing output that fails `json.loads()`.

**Current Behaviour:** The existing `except` block in `synthesizer_node` catches the parse failure and returns a safe fallback `AlphaSignal` with `confidence: 0.0` and `direction: Neutral`. The pipeline does not crash and the SSE stream completes normally.

**Status:** Tracked as v2.0 technical debt. Two mitigations are planned:

| Priority | Mitigation | Notes |
|---|---|---|
| v1.1 | Add `json-repair` pre-pass inside `_parse_alpha_signal()` | Drop-in, no schema changes |
| v1.2 | Migrate synthesizer to `llm.with_structured_output(AlphaSignal)` | API-level enforcement; eliminates the problem class |

---

## Project Structure

```
alpha_engine/
├── backend/
│   ├── main.py          # FastAPI app, SSE event generator
│   ├── graph.py         # LangGraph graph: nodes, edges, sanitizer, router
│   ├── state.py         # AgentState, AlphaSignal schema, message reducer
│   ├── llm.py           # Groq LLM configuration
│   ├── embed.py         # Gemini embedding helper
│   ├── security.py      # Internal API secret validation
│   └── tools/
│       ├── quant_tool.py   # python_repl — live market data via yfinance
│       └── fund_tool.py    # pinecone_search — SEC filing vector retrieval
├── frontend/            # Next.js application
├── ingestion/
│   └── api_ingest.py    # PDF ingestion router + job status tracker
├── scripts/
│   ├── start_server.ps1     # Windows: safe uvicorn launcher (port cleanup)
│   ├── test_local_ingest.ps1
│   ├── audit_pinecone.py
│   └── smoke_test_retrieval.py
└── .env.example         # Required environment variables (template)
```

---

## Local Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Pinecone account (Serverless index, `us-east-1`)
- API keys for Groq, Gemini, and Pinecone

---

### 1. Clone & Configure Environment

```bash
git clone https://github.com/<your-username>/alpha-engine.git
cd alpha_engine
```

Copy the environment template and fill in your keys:

```bash
cp .env.example .env
```

Required variables in `.env`:

```env
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIza...
PINECONE_API_KEY=pcsk_...
PINECONE_INDEX_NAME=alpha-engine
INTERNAL_API_SECRET=<any-random-secret>
VERCEL_FRONTEND_URL=http://localhost:3000   # or your deployed frontend URL
```

---

### 2. Backend Setup

```powershell
# From alpha_engine/backend/
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Start the backend (recommended — handles port cleanup automatically):**

```powershell
# From alpha_engine/ root
powershell -ExecutionPolicy Bypass -File scripts\start_server.ps1
```

Or manually:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Backend available at: `http://127.0.0.1:8000`

---

### 3. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend available at: `http://localhost:3000`

---

### 4. Ingest a PDF (Optional — for fund analysis)

```bash
curl -X POST http://127.0.0.1:8000/api/ingest \
  -H "X-Internal-Secret: <your-INTERNAL_API_SECRET>" \
  -F "file=@/path/to/msft_8k.pdf" \
  -F "ticker=MSFT" \
  -F "fiscal_year=2026" \
  -F "filing_type=8-K"
```

---

### 5. Run an Analysis Query

```bash
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "Analyze MSFT risk and live market data", "session_id": "demo-001"}'
```

The response streams SSE events: `agent_status`, `agent_action`, `agent_token`, `alpha_signal`, `done`.

---


## License

MIT
