"""
LightRAG runtime — lazy singleton.

The first call to `get_lightrag()` instantiates LightRAG with our
Vertex embeddings + OpenRouter LLM adapters and our SQLite/file
storage. Subsequent calls return the same instance.

Storage layout (under LIGHTRAG_WORKING_DIR, default ./.lightrag):
  ./graph_chunk_entity_relation.graphml   — the actual graph
  ./vdb_entities.json                     — entity vectors
  ./vdb_relationships.json                — edge vectors
  ./vdb_chunks.json                       — chunk vectors
  ./kv_store_*.json                       — KV stores for full text

For a Railway deploy, set LIGHTRAG_WORKING_DIR to a path on the volume
mount (e.g. /data/lightrag) so the graph survives restarts.

When `lightrag-hku` isn't installed (default state in current
requirements.txt), `get_lightrag()` raises `LightragNotInstalled`.
The router catches this and returns a 503 — the rest of Cerebro keeps
working. To enable: add `lightrag-hku>=1.0.0` to requirements.txt
and `pip install -r requirements.txt`.
"""
import os
from typing import TYPE_CHECKING


WORKING_DIR = os.getenv("LIGHTRAG_WORKING_DIR", "./.lightrag")


class LightragNotInstalled(RuntimeError):
    pass


_instance = None


def _ensure_dir():
    os.makedirs(WORKING_DIR, exist_ok=True)


def get_lightrag():
    """Return the shared LightRAG instance. Lazy: builds on first call.

    Raises LightragNotInstalled if the underlying package is missing —
    callers translate that to a 503 with a helpful message.
    """
    global _instance
    if _instance is not None:
        return _instance

    try:
        from lightrag import LightRAG  # type: ignore
    except ImportError as e:
        raise LightragNotInstalled(
            "lightrag-hku is not installed. Add `lightrag-hku>=1.0.0` to "
            "requirements.txt and `pip install -r requirements.txt`."
        ) from e

    from .embeddings_adapter import lightrag_embed
    from .llm_adapter import (
        lightrag_build_complete,
        lightrag_query_complete,
    )

    _ensure_dir()

    # LightRAG's constructor signature varies between versions; we keep
    # the call narrow to what's stable: working_dir + LLM + embed.
    _instance = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=lightrag_query_complete,
        embedding_func=lightrag_embed,
        # Override the cheap-extraction model with our build-mode adapter
        # so entity/relation extraction goes to Haiku, not Sonnet.
        # (Newer LightRAG versions expose this as `entity_extract_func`;
        # older as `cheap_model_func`. We try both via setattr for
        # forward/backward compat — unrecognized attrs are no-ops.)
    )
    # Best-effort attach of the build-time func:
    for attr in ("cheap_model_func", "entity_extract_func", "_entity_extract_func"):
        try:
            setattr(_instance, attr, lightrag_build_complete)
        except Exception:
            pass

    return _instance


async def reset():
    """Drop the in-memory singleton. The on-disk store is untouched —
    next call will re-attach to it. Used by ops endpoints."""
    global _instance
    _instance = None
