import os
from dotenv import load_dotenv
load_dotenv()

from pinecone import Pinecone
from backend.embed import embed_text

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index(os.getenv("PINECONE_INDEX_NAME"))

print("Embedding query vector...")
q = embed_text("revenue growth risk factors data center")

res = index.query(
    vector=q,
    top_k=3,
    namespace="sec-10k",
    filter={
        "$and": [
            {"ticker": {"$eq": "NVDA"}},
            {"fiscal_year": {"$gte": 2026}},
        ]
    },
    include_metadata=True,
)

print(f"Results: {len(res.matches)}")
for m in res.matches:
    fy_raw = m.metadata.get("fiscal_year")
    # NOTE: Pinecone SDK always deserializes numeric metadata as float.
    # Cast to int for display/assertion — the stored value is semantically an int.
    fy = int(fy_raw) if isinstance(fy_raw, float) and fy_raw == int(fy_raw) else fy_raw
    print(f"  score={m.score:.4f} | fy={fy} (int) | {m.metadata['text'][:100]}")

assert len(res.matches) > 0, "FAIL: 0 results returned"

for m in res.matches:
    fy_raw = m.metadata.get("fiscal_year")
    assert isinstance(fy_raw, (int, float)), f"FAIL: fiscal_year has unexpected type {type(fy_raw)}"
    if isinstance(fy_raw, float):
        assert fy_raw == int(fy_raw), f"FAIL: fiscal_year {fy_raw} has fractional part (not a clean year)"

assert res.matches[0].score > 0.35, f"FAIL: top score {res.matches[0].score:.4f} < 0.35"

print(f"RETRIEVAL TEST PASSED (top score={res.matches[0].score:.4f})")
print("NOTE: Pinecone SDK returns all numeric metadata as float — cast to int at read time.")
