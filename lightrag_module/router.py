"""
LightRAG FastAPI router — mounted in main.py.

Three endpoints:
  POST /lightrag/insert    — feed a batch of chunks into the graph
  POST /lightrag/query     — query the graph (local | global | hybrid)
  GET  /lightrag/health    — quick check + counts (entities/relations)

All endpoints respond gracefully when lightrag-hku isn't installed:
they return 503 with a hint to install the package, not 500. That way
this module ships dormant in production and the rest of Cerebro keeps
working unaffected.
"""
import os
from typing import Optional, Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .runtime import get_lightrag, LightragNotInstalled


lightrag_router = APIRouter(prefix="/lightrag", tags=["lightrag"])


# ─── Request models ──────────────────────────────────────────────────

class InsertChunk(BaseModel):
    """One chunk to feed into LightRAG's graph builder.

    Fields beyond `content` are optional metadata that LightRAG's newer
    versions can attach to the entity nodes. Older versions ignore.
    """
    chunk_id: str
    content: str
    source_type: Optional[str] = None       # 'sil_expediente' | 'reglamento' | …
    source_ref: Optional[str] = None        # 'Exp. 22.290 — texto_base'
    expediente_numero: Optional[str] = None
    comision: Optional[str] = None
    fecha: Optional[str] = None


class InsertRequest(BaseModel):
    chunks: list[InsertChunk]


class QueryRequest(BaseModel):
    query: str
    mode: Literal["local", "global", "hybrid", "naive"] = "hybrid"
    deep_insight: bool = False
    top_k: int = Field(default=10, ge=1, le=40)


# ─── Helpers ─────────────────────────────────────────────────────────

def _503_when_missing():
    """Convert LightragNotInstalled to a clear 503 with install hint."""
    return HTTPException(
        status_code=503,
        detail={
            "ok": False,
            "error": "lightrag_not_installed",
            "fix": "Add `lightrag-hku>=1.0.0` to requirements.txt then `pip install -r requirements.txt`.",
        },
    )


# ─── Endpoints ───────────────────────────────────────────────────────

@lightrag_router.post("/insert")
async def insert_chunks(req: InsertRequest):
    """Feed a batch of chunks into the graph. LightRAG dedupes by
    content hash internally; passing the same chunk twice is a no-op
    on the second call."""
    try:
        rag = get_lightrag()
    except LightragNotInstalled:
        raise _503_when_missing()

    # LightRAG accepts either a single string or list[str] via `insert`.
    # We pass the raw text bodies; metadata is best-effort and depends
    # on the lightrag-hku version supporting it.
    bodies = [c.content for c in req.chunks]

    try:
        # Newer LightRAG: `ainsert(text)` accepts list. Older: needs loop.
        if hasattr(rag, "ainsert"):
            await rag.ainsert(bodies)
        else:
            for body in bodies:
                rag.insert(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(e)})

    return {
        "ok": True,
        "ingested": len(bodies),
        "total_chars": sum(len(b) for b in bodies),
    }


@lightrag_router.post("/query")
async def query_graph(req: QueryRequest):
    """Query the graph. Returns the synthesized answer + (when possible)
    the entities/relations that contributed."""
    try:
        rag = get_lightrag()
    except LightragNotInstalled:
        raise _503_when_missing()

    # Lazy import to keep cold start cheap.
    from lightrag import QueryParam  # type: ignore

    param = QueryParam(mode=req.mode, top_k=req.top_k)
    try:
        if hasattr(rag, "aquery"):
            answer = await rag.aquery(req.query, param=param)
        else:
            # Older versions exposed sync only.
            answer = rag.query(req.query, param=param)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(e)})

    return {
        "ok": True,
        "mode": req.mode,
        "query": req.query,
        "answer": answer,
        # Some versions return the raw answer string; richer versions
        # ship a dict with `context`/`entities`. We pass through as-is
        # under `meta` so the BFF can surface citations to the UI.
        "meta": (
            answer if isinstance(answer, dict) else None
        ),
    }


@lightrag_router.get("/health")
async def lightrag_health():
    """Counts of entities/relations, working dir size, model config.
    Designed so /health/deep on the BFF can include this."""
    working_dir = os.getenv("LIGHTRAG_WORKING_DIR", "./.lightrag")

    # If the package isn't installed, return a degraded but useful
    # health payload (200, not 503) so monitoring doesn't pageout.
    try:
        rag = get_lightrag()
        installed = True
        entity_count = None
        relation_count = None
        # Best-effort introspection. LightRAG's internals vary by version.
        try:
            entity_count = await rag.entities_vdb.acount() if hasattr(rag, "entities_vdb") else None
        except Exception:
            pass
        try:
            relation_count = (
                await rag.relationships_vdb.acount() if hasattr(rag, "relationships_vdb") else None
            )
        except Exception:
            pass
    except LightragNotInstalled:
        installed = False
        entity_count = None
        relation_count = None

    # Compute disk footprint of the working dir, if it exists.
    bytes_on_disk = 0
    if os.path.isdir(working_dir):
        for root, _dirs, files in os.walk(working_dir):
            for fn in files:
                try:
                    bytes_on_disk += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass

    return {
        "ok": True,
        "installed": installed,
        "working_dir": working_dir,
        "working_dir_mb": round(bytes_on_disk / (1024 * 1024), 2),
        "entity_count": entity_count,
        "relation_count": relation_count,
        "build_model": os.getenv("LIGHTRAG_BUILD_MODEL", "anthropic/claude-haiku-4.5"),
        "query_model": os.getenv("LIGHTRAG_QUERY_MODEL", "anthropic/claude-sonnet-4.6"),
    }
