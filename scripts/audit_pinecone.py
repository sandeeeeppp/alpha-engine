"""
Pinecone Metadata Audit & Repair Script
Run from alpha_engine/ root:
    backend\\.venv\\Scripts\\python.exe scripts/audit_pinecone.py
"""
import os
import logging
from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")


def audit_and_repair(namespace: str = "sec-10k"):
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    index = pc.Index(os.getenv("PINECONE_INDEX_NAME"))

    stats = index.describe_index_stats()
    logging.info(f"Index stats: {stats}")

    ns_count = stats.get("namespaces", {}).get(namespace, {}).get("vector_count", 0)
    if ns_count == 0:
        logging.info(f"Namespace '{namespace}' is empty. No audit needed.")
        return

    logging.info(f"Auditing {ns_count} vectors in '{namespace}'...")
    repaired = 0
    deleted = 0

    for id_batch in index.list(namespace=namespace):
        fetch_resp = index.fetch(ids=id_batch, namespace=namespace)
        for vec_id, vec_data in fetch_resp.vectors.items():
            meta = vec_data.metadata or {}

            # Delete dimension-mismatched vectors (from old embedding models)
            if len(vec_data.values) != 768:
                logging.warning(
                    f"  DELETE {vec_id}: dim={len(vec_data.values)} (expected 768)"
                )
                index.delete(ids=[vec_id], namespace=namespace)
                deleted += 1
                continue

            # Fix fiscal_year stored as str or float → must be int
            fy = meta.get("fiscal_year")
            if fy is not None and not isinstance(fy, (int, bool)) and not (
                isinstance(fy, float) and fy != int(fy)
            ):
                try:
                    corrected = int(fy)
                    index.update(
                        id=vec_id,
                        set_metadata={"fiscal_year": corrected},
                        namespace=namespace,
                    )
                    logging.info(
                        f"  FIXED {vec_id}: fiscal_year {fy!r} ({type(fy).__name__}) -> {corrected}"
                    )
                    repaired += 1
                except (ValueError, TypeError):
                    logging.error(
                        f"  ERROR {vec_id}: Cannot cast fiscal_year={fy!r} to int"
                    )

    logging.info(f"\nAudit complete. Repaired: {repaired}, Deleted: {deleted}")


if __name__ == "__main__":
    audit_and_repair()
