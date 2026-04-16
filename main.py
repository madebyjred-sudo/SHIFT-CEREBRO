"""
Shift Lab Swarm Cerebro v3 — Legio Digitalis Latina
Entry point: mounts all routers, configures CORS, starts uvicorn.

Architecture (post-refactor):
  config/       → database.py, models.py
  agents/       → skills/*.yaml, registry.py, context.py
  graph/        → state.py, nodes.py, router.py, web_search.py, builder.py, synthesizer.py
  peaje/        → router.py, extractor.py, ingest.py
  punto_medio_pkg/ → router.py
  adapters/     → studio_adapter.py, embed_adapter.py, export_adapter.py
  (standalone)  → punto_medio.py, pii_scrubber.py, tenant_constitution.py, tenant_api.py, tools/
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════
# APP INIT
# ═══════════════════════════════════════════════════════════════
app = FastAPI(title="Shift Lab Swarm Cerebro v3 - Legio Digitalis Latina")

# CORS
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:3001,http://localhost:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════
# MOUNT ROUTERS
# ═══════════════════════════════════════════════════════════════
from tenant_api import router as tenant_router
from peaje.router import peaje_router
from punto_medio_pkg.router import punto_medio_router
from adapters.studio_adapter import studio_router
from adapters.export_adapter import export_router
from adapters.embed_adapter import embed_router

app.include_router(tenant_router)
app.include_router(peaje_router)
app.include_router(punto_medio_router)
app.include_router(studio_router)
app.include_router(export_router)
app.include_router(embed_router)

# ═══════════════════════════════════════════════════════════════
# HEALTH ENDPOINT
# ═══════════════════════════════════════════════════════════════
from agents.registry import AGENTS

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "shift-cerebro-swarm-v3-legio-digitalis",
        "version": "v3.1.0-mcp",
        "agents_count": len(AGENTS),
        "agents": [info["name"] for info in AGENTS.values()],
        "features": ["langgraph_statgraph", "llm_router", "multi_agent_sequential", "synthesizer", "embed_copilot", "mcp_servers", "dynamic_rag", "pii_scrubber", "taxonomy_validation", "debate_ingestion", "punto_medio", "document_generation"]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
