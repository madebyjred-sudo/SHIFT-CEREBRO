"""
Vertex AI embeddings adapter for LightRAG.

LightRAG accepts an arbitrary async callable for embeddings: it gives
us a list of strings, expects a list of float vectors back. We wrap
Vertex `gemini-embedding-001` (3072d, multilingual) which CL2 already
uses elsewhere — no second embedding model to maintain, no second
budget to track.

Embedding task type matters:
  - RETRIEVAL_DOCUMENT for the chunks we index (build time)
  - RETRIEVAL_QUERY    for the user's query (query time)
LightRAG calls us for both; we infer task type from a kwarg passed by
LightRAG's internals (defaults to DOCUMENT to match the build path).

Concurrency: we cap parallelism at 8 — Vertex's quota is 600 RPM by
default, and we share that bucket with the SIL bulk downloader and the
process-sil-docs script. Going higher leads to 429s.
"""
import os
from typing import Iterable
import asyncio


VERTEX_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
VERTEX_MODEL = os.getenv("VERTEX_EMBEDDING_MODEL", "gemini-embedding-001")
VERTEX_DIM = int(os.getenv("VERTEX_EMBEDDING_DIM", "3072"))
EMBED_CONCURRENCY = int(os.getenv("LIGHTRAG_EMBED_CONCURRENCY", "8"))


_client = None


def _get_client():
    """Lazy import + lazy init. Keeps cold-start of cerebro fast and
    means missing google-cloud-aiplatform on dev machines doesn't block
    everything else from importing."""
    global _client
    if _client is not None:
        return _client
    from google.cloud import aiplatform_v1  # type: ignore
    from google.cloud.aiplatform_v1.services.prediction_service import (
        PredictionServiceAsyncClient,
    )
    _client = PredictionServiceAsyncClient(
        client_options={"api_endpoint": f"{VERTEX_LOCATION}-aiplatform.googleapis.com"}
    )
    return _client


def _endpoint() -> str:
    project = os.getenv("GCP_PROJECT_ID")
    if not project:
        raise RuntimeError("GCP_PROJECT_ID not set — cannot use Vertex embeddings")
    return (
        f"projects/{project}/locations/{VERTEX_LOCATION}"
        f"/publishers/google/models/{VERTEX_MODEL}"
    )


async def _embed_one(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    from google.protobuf import struct_pb2  # type: ignore
    from google.cloud.aiplatform_v1.types import PredictRequest  # type: ignore

    client = _get_client()
    instance = struct_pb2.Value()
    instance.struct_value.update({"content": text, "task_type": task_type})
    parameters = struct_pb2.Value()
    parameters.struct_value.update({"outputDimensionality": VERTEX_DIM})

    request = PredictRequest(
        endpoint=_endpoint(),
        instances=[instance],
        parameters=parameters,
    )
    response = await client.predict(request=request)
    pred = response.predictions[0]
    # The protobuf Struct→dict conversion path; LightRAG only cares about
    # the vector list at the end.
    values = list(pred["embeddings"]["values"])  # type: ignore[index]
    if not values:
        raise RuntimeError("vertex predict: missing embeddings.values")
    return values


async def embed_texts(
    texts: Iterable[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Embed a batch of texts. Used by LightRAG's index builder. Bounded
    concurrency so we don't blow Vertex quota."""
    texts_list = list(texts)
    if not texts_list:
        return []

    sem = asyncio.Semaphore(EMBED_CONCURRENCY)
    results: list[list[float] | None] = [None] * len(texts_list)

    async def _bounded(idx: int, t: str):
        async with sem:
            results[idx] = await _embed_one(t, task_type=task_type)

    await asyncio.gather(*[_bounded(i, t) for i, t in enumerate(texts_list)])
    out = [r for r in results if r is not None]
    if len(out) != len(texts_list):
        raise RuntimeError("vertex embed: missing results in batch")
    return out


# LightRAG's contract: a callable that takes list[str] and returns
# numpy.ndarray with shape (n, dim). We wrap embed_texts and convert.
async def lightrag_embed(texts: list[str]):
    """LightRAG-compatible embedding function. Numpy import deferred so
    importing this module is cheap on cold start."""
    import numpy as np  # type: ignore

    vectors = await embed_texts(texts, task_type="RETRIEVAL_DOCUMENT")
    return np.array(vectors, dtype=np.float32)


# Tag the function with the dimensions LightRAG inspects to size its
# vector store. Using setattr keeps mypy quiet.
setattr(lightrag_embed, "embedding_dim", VERTEX_DIM)
setattr(lightrag_embed, "max_token_size", 8000)
