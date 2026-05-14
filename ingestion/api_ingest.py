import asyncio
import logging
import os
import uuid
import tempfile
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import Pinecone

from backend.embed import embed_batch
from backend.security import verify_internal_secret

load_dotenv()

_pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
_index = _pc.Index(os.getenv("PINECONE_INDEX_NAME"))  # NO suffix

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=600,
    chunk_overlap=100,
    separators=["\n\n", "\n", ". ", " ", ""],
)

ingest_router = APIRouter(tags=["ingestion"])

RECOVERY_LOG = "ingestion_recovery.log"


async def _do_ingest(
    file_bytes: bytes,
    filename: str,
    ticker: str,
    fiscal_year: int,
    item_section: str,
) -> None:
    """
    Core ingestion logic: load PDF → split → embed → upsert.
    Wrapped in asyncio.shield by _background_ingest to protect from cancellation.
    Runs in the event loop via loop.run_in_executor for blocking calls.
    """
    tmp_path: Optional[str] = None
    loop = asyncio.get_event_loop()

    def _sync_ingest() -> None:
        """Blocking portion — runs in thread pool via run_in_executor."""
        nonlocal tmp_path
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp_path = tmp.name
        tmp.write(file_bytes)
        tmp.close()

        raw_docs = PyPDFLoader(tmp_path).load()
        if not raw_docs or all(not d.page_content.strip() for d in raw_docs):
            logging.error(f"[ingest] PDF {filename} has no extractable text.")
            return

        chunks = _splitter.split_documents(raw_docs)
        logging.info(f"[ingest] {filename}: {len(chunks)} chunks. Starting batch embed.")

        texts = [
            f"Context: Company: {ticker} | Year: {fiscal_year} "
            f"| Section: {item_section} | Source: {filename}\n\n"
            + chunk.page_content
            for chunk in chunks
        ]

        # 100 texts per API call (Gemini hard limit) — 5s inter-batch sleep enforced in embed_batch
        embeddings = embed_batch(texts)

        vectors = [
            {
                "id": f"{ticker}-{fiscal_year}-{item_section}-{uuid.uuid4().hex[:8]}",
                "values": embeddings[i],
                "metadata": {
                    "ticker": ticker,
                    "fiscal_year": fiscal_year,   # int — CRITICAL for Pinecone $gte filter
                    "item_section": item_section,
                    "form_type": "uploaded_pdf",
                    "chunk_type": "text",
                    "source_filename": filename,
                    "text": texts[i],
                },
            }
            for i in range(len(embeddings))
        ]

        UPSERT_BATCH = 100
        for i in range(0, len(vectors), UPSERT_BATCH):
            _index.upsert(vectors=vectors[i : i + UPSERT_BATCH], namespace="sec-10k")

        logging.info(f"[ingest] SUCCESS: {filename} -> {len(vectors)} vectors upserted.")

        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
            tmp_path = None

    await loop.run_in_executor(None, _sync_ingest)

    # Cleanup if _sync_ingest raised before unlinking
    if tmp_path and os.path.exists(tmp_path):
        os.unlink(tmp_path)


async def _background_ingest(
    file_bytes: bytes,
    filename: str,
    ticker: str,
    fiscal_year: int,
    item_section: str,
) -> None:
    """
    Async background task wrapper.
    asyncio.shield protects the critical Pinecone upsert from uvicorn reload cancellation,
    preventing partial vector writes to Pinecone.
    """
    try:
        await asyncio.shield(
            _do_ingest(file_bytes, filename, ticker, fiscal_year, item_section)
        )
    except asyncio.CancelledError:
        logging.error(
            f"[ingest] INTERRUPTED: {filename} — uvicorn reload mid-ingest. "
            f"Partial upsert may exist. Logging to {RECOVERY_LOG}."
        )
        with open(RECOVERY_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"INTERRUPTED: ticker={ticker} fy={fiscal_year} "
                f"section={item_section} file={filename}\n"
            )
        raise
    except Exception as e:
        logging.error(f"[ingest] FAILED for {filename}: {e}", exc_info=True)


@ingest_router.post("/ingest", dependencies=[Depends(verify_internal_secret)])
async def ingest_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    ticker: str = Form(...),
    fiscal_year: int = Form(...),
    item_section: str = Form(default="uploaded_report"),
):
    if file.content_type != "application/pdf":
        raise HTTPException(400, f"Only PDF accepted. Got: {file.content_type}")

    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "ticker must be non-empty.")
    if not (1900 <= fiscal_year <= 2100):
        raise HTTPException(400, "fiscal_year must be valid 4-digit year.")

    file_bytes = await file.read()

    # Return 202 IMMEDIATELY — processing continues in background via asyncio.shield
    background_tasks.add_task(
        _background_ingest, file_bytes, file.filename, ticker, fiscal_year, item_section
    )
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": "PDF queued for background ingestion. Check server logs for completion.",
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "filename": file.filename,
        },
    )
