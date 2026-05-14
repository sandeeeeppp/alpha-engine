# Alpha Engine ⚡

> A production-grade Agentic RAG pipeline for real-time financial analysis.

Alpha Engine combines a **LangGraph multi-agent orchestrator** with **Pinecone vector search** and **live market data** to generate structured `AlphaSignal` outputs — think of it as a hedge fund analyst in an API.

---

## Features

| Capability | Detail |
|---|---|
| **Multi-Agent Orchestration** | Supervisor → Quant → Fund → Synthesizer hub-and-spoke graph |
| **Live Market Data** | Yahoo Finance via `python_repl` tool (price, volatility, 90d momentum) |
| **SEC Filing Retrieval** | Pinecone vector search over ingested 8-K/10-K PDFs (`pinecone_search` tool) |
| **Real-Time PDF Ingestion** | FastAPI endpoint with per-job status tracking and progress streaming |
| **Structured Output** | Pydantic `AlphaSignal` schema: ticker, direction, volatility, momentum, confidence |
| **SSE Streaming** | Server-Sent Events pipeline for shell-like agent terminal experience |
| **Groq Strict Mode Compatible** | Pre-flight tool-call sanitizer prevents hallucinated tool names from crashing the LLM |

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

**Start the backend (recommended — handles port cleanup):**

```powershell
# From alpha_engine/ root
powershell -ExecutionPolicy Bypass -File scripts\start_server.ps1
```

Or manually:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Backend will be available at: `http://127.0.0.1:8000`

---

### 3. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend will be available at: `http://localhost:3000`

---

### 4. Ingest a PDF (Optional — for fund analysis)

Use the ingestion endpoint to load an SEC filing into Pinecone:

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

## Agent Pipeline

```
User Query
    │
    ▼
[memory_trim] → [supervisor]
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
       [quant]              [fund]
    (python_repl)      (pinecone_search)
          │                    │
          └─────────┬──────────┘
                    ▼
             [synthesizer]
                    │
                    ▼
             AlphaSignal JSON
```

The Supervisor uses a **deterministic ToolMessage counter** (not LLM judgment) to enforce the two-step sequence, with a pre-flight sanitizer that intercepts any hallucinated tool names before Groq's strict validator sees them.

---

## Environment Variable Reference

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | ✅ | Groq API key (supervisor LLM) |
| `GEMINI_API_KEY` | ✅ | Google AI key (embeddings + synthesizer) |
| `PINECONE_API_KEY` | ✅ | Pinecone API key |
| `PINECONE_INDEX_NAME` | ✅ | Name of your Pinecone serverless index |
| `INTERNAL_API_SECRET` | ✅ | Secret for ingestion endpoint auth |
| `VERCEL_FRONTEND_URL` | ⚠️ | Frontend origin for CORS (default: `http://localhost:3000`) |

---

## License

MIT
