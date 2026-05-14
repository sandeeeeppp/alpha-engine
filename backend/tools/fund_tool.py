import os
from dotenv import load_dotenv
from pinecone import Pinecone
from langchain_core.tools import tool
from backend.embed import embed_text

load_dotenv()

_pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
_index = _pc.Index(os.getenv("PINECONE_INDEX_NAME"))


@tool
def pinecone_search(query: str, ticker: str, fiscal_year: int) -> str:
    """
    Searches Pinecone sec-10k namespace for qualitative fundamental risk context.
    Returns [FUND] tagged result for supervisor gatekeeper routing.
    """
    try:
        vector = embed_text(query)
        results = _index.query(
            vector=vector,
            top_k=5,
            namespace="sec-10k",
            filter={
                "ticker": {"$eq": str(ticker).upper()},
                "fiscal_year": {"$gte": int(fiscal_year)},  # CRITICAL: always cast to int
            },
            include_metadata=True,
        )

        if not results.matches:
            return (
                f"[FUND] No fundamental data found for {ticker} FY{fiscal_year} in the index. "
                f"Proceed with available quantitative data only."
            )

        chunks = []
        for m in results.matches:
            fy = int(m.metadata.get("fiscal_year", 0))  # cast float→int from Pinecone
            section = m.metadata.get("item_section", "unknown")
            text = m.metadata.get("text", "")[:500]
            chunks.append(
                f"[Section {section} | FY{fy} | Score {m.score:.3f}]\n{text}"
            )

        return "[FUND] Fundamental Risk Context:\n\n" + "\n\n---\n\n".join(chunks)

    except Exception as e:
        return f"[FUND] Retrieval failed: {str(e)[:200]}. Proceed with quantitative data."
