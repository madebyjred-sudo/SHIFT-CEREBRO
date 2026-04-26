"""
shift-cerebro/lightrag_module — graph-augmented RAG over the SIL corpus.

This module hosts a LightRAG instance (HK PolyU, Aug 2024 paper) inside
Cerebro's existing FastAPI process. LightRAG turns the SIL corpus +
Reglamento + plenarias transcripts into a dual-level graph:

  • low-level entities: diputados, expedientes, comisiones, dictámenes,
    leyes, números de gaceta, partidos políticos, instituciones citadas
    (CCSS, INS, MEIC, Procuraduría, etc.).
  • high-level keywords: themes that surface across the corpus
    (traslado de competencias, dispensa de trámite, control de
    constitucionalidad, presupuesto extraordinario, …).

A query against the graph returns:
  - "local" mode: subgraph of entities directly relevant to the query
    (e.g. "qué dijo Muñoz Céspedes sobre traslado de riesgos") —
    walks edges from a seed entity.
  - "global" mode: high-level themes that intersect the query (e.g.
    "qué patrones políticos emergen en proyectos de salud") — uses
    the LLM-generated keyword index.

Why LightRAG (not GraphRAG): we get 70% of GraphRAG's value at ~50%
build cost and ~30% storage. We can layer Leiden community detection
on top later — see ROADMAP-POST-DEMO §1.

Storage: SQLite + on-disk pickle files at ${LIGHTRAG_WORKING_DIR}.
A Railway volume mount makes this persistent across deploys without
adding Neo4j to the stack.

Public surface:
  - `runtime.get_lightrag()` — lazy singleton (instantiates on first
    use). Configures Vertex embeddings + Anthropic via OpenRouter.
  - `router.lightrag_router` — FastAPI endpoints (mounted in main.py).

NOT YET INSTALLED in production. Add `lightrag-hku>=0.1.0` to
requirements.txt and pip install before first build. The runtime
auto-defers to a stub when the package is missing so the rest of
Cerebro keeps working.
"""

__all__ = ["runtime", "router", "embeddings_adapter", "llm_adapter"]
