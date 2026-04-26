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
import asyncio
import os
from typing import TYPE_CHECKING


WORKING_DIR = os.getenv("LIGHTRAG_WORKING_DIR", "./.lightrag")


class LightragNotInstalled(RuntimeError):
    pass


_instance = None
_init_lock: asyncio.Lock | None = None
_initialized = False


def _ensure_dir():
    os.makedirs(WORKING_DIR, exist_ok=True)


async def get_lightrag():
    """Return the shared, fully-initialized LightRAG instance.

    LightRAG ≥1.4 splits construction from storage initialization:
    `initialize_storages()` must run before the first insert/query or
    the underlying KV/vector/doc-status stores raise. We do both lazily
    on first call, guarded by an asyncio.Lock so concurrent first
    callers don't race the init.

    Raises LightragNotInstalled if the underlying package is missing —
    callers translate that to a 503 with a helpful message.
    """
    global _instance, _init_lock, _initialized
    if _instance is not None and _initialized:
        return _instance
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    async with _init_lock:
        # Re-check inside the lock — another task may have finished init
        # while we were waiting.
        if _instance is not None and _initialized:
            return _instance

        try:
            from lightrag import LightRAG  # type: ignore
        except ImportError as e:
            raise LightragNotInstalled(
                "lightrag-hku is not installed. Add `lightrag-hku>=1.0.0` to "
                "requirements.txt and `pip install -r requirements.txt`."
            ) from e

        from .embeddings_adapter import build_lightrag_embed
        from .llm_adapter import (
            lightrag_build_complete,
            lightrag_query_complete,
        )

        _ensure_dir()

        if _instance is None:
            # `embedding_func` MUST be an `EmbeddingFunc` wrapper instance
            # (LightRAG ≥1.4 accesses `.func` and `.embedding_dim` directly).
            _instance = LightRAG(
                working_dir=WORKING_DIR,
                llm_model_func=lightrag_query_complete,
                embedding_func=build_lightrag_embed(),
                # We don't pass entity_extract_func at construction time —
                # the field name varies across LightRAG versions. Best-effort
                # setattr below covers both old and new APIs.
            )
            for attr in ("cheap_model_func", "entity_extract_func", "_entity_extract_func"):
                try:
                    setattr(_instance, attr, lightrag_build_complete)
                except Exception:
                    pass

        # initialize_storages is idempotent within a single instance but the
        # LightRAG team treats double-init as a no-op on most stores. We
        # still gate with the _initialized flag so our own logic stays clean.
        await _instance.initialize_storages()
        # initialize_pipeline_status is required for /insert in 1.4+; some
        # builds expose it as a free function on lightrag.kg.shared_storage.
        try:
            from lightrag.kg.shared_storage import initialize_pipeline_status  # type: ignore
            await initialize_pipeline_status()
        except ImportError:
            pass

        _initialized = True
        return _instance


async def reset():
    """Drop the in-memory singleton. The on-disk store is untouched —
    next call will re-attach to it. Used by ops endpoints."""
    global _instance, _initialized
    _instance = None
    _initialized = False
