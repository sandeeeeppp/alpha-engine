import os
import time
import random
import logging
from google import genai as google_genai
from google.genai import types

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768
MAX_RETRIES = 5
BASE_DELAY = 4.0


def embed_text(text: str) -> list[float]:
    """Single text embed with exponential backoff. Used by fund_tool for queries."""
    client = google_genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            result = client.models.embed_content(
                model=EMBED_MODEL,
                contents=text,
                config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
            )
            return list(result.embeddings[0].values)
        except Exception as e:
            last_error = e
            err = str(e).lower()
            if any(x in err for x in ["429", "resource_exhausted", "quota"]):
                delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 1.5)
                logging.warning(
                    f"[embed_text] Rate limit hit. Retry {attempt + 1}/{MAX_RETRIES} in {delay:.1f}s"
                )
                time.sleep(delay)
                continue
            raise
    raise RuntimeError(
        f"embed_text failed after {MAX_RETRIES} retries. Last: {last_error}"
    )


def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Batch embed texts in sequential 100-item API calls.
    gemini-embedding-001 hard limit: 100 inputs per embed_content request.
    A mandatory 5-second inter-batch sleep keeps requests well under the
    Gemini free-tier 15 RPM limit (60s / 15 = 4s minimum gap).
    Includes exponential backoff retry on 429 within each batch.
    """
    if not texts:
        return []

    client = google_genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    BATCH_SIZE = 100  # Gemini embed_content hard limit per request
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                result = client.models.embed_content(
                    model=EMBED_MODEL,
                    contents=batch,
                    config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
                )
                all_embeddings.extend([list(e.values) for e in result.embeddings])
                break
            except Exception as e:
                last_error = e
                err = str(e).lower()
                if any(x in err for x in ["429", "resource_exhausted", "quota"]):
                    delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 2)
                    logging.warning(
                        f"[embed_batch] Batch {batch_num} rate limited. "
                        f"Retry {attempt + 1}/{MAX_RETRIES} in {delay:.1f}s"
                    )
                    time.sleep(delay)
                    continue
                raise
        else:
            raise RuntimeError(
                f"embed_batch failed on batch {batch_num}: {last_error}"
            )

        # Sleep between batches to stay under Gemini 15 RPM free-tier limit.
        # 60s / 15 RPM = 4s minimum gap — use 5s for a safe margin.
        # Skip sleep after the final batch to avoid unnecessary delay.
        is_last_batch = (i + BATCH_SIZE) >= len(texts)
        if not is_last_batch:
            logging.info(
                f"[embed_batch] Batch {batch_num} complete "
                f"({len(batch)} texts). Sleeping 5s before next batch."
            )
            time.sleep(5)

    return all_embeddings
