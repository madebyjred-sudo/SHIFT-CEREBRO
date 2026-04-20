"""Agents Market Adapter — /market/agents.json

Serves the 15 Cerebro agents in LobeChat's AGENTS_INDEX_URL JSON format
so they appear natively in the LobeChat Discover/Market UI.

Schema reverse-engineered from https://chat-agents.lobehub.com/index.en-US.json
"""
import os
import yaml
from typing import Dict, Any, List

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from agents.registry import AGENTS

market_router = APIRouter(prefix="/market", tags=["market"])

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "agents", "skills")

# ═══════════════════════════════════════════════════════════════
# AGENT METADATA (emoji, color, pod — from frontend agentRegistry.ts)
# ═══════════════════════════════════════════════════════════════

AGENT_META_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "carmen":    {"emoji": "👑", "color": "#9333EA", "tags": ["c-suite", "estrategia", "vision", "pitch"]},
    "roberto":   {"emoji": "💰", "color": "#059669", "tags": ["finanzas", "cfo", "presupuesto", "runway"]},
    "valentina": {"emoji": "🌸", "color": "#EC4899", "tags": ["marketing", "cmo", "branding", "posicionamiento"]},
    "diego":     {"emoji": "🟢", "color": "#7C3AED", "tags": ["producto", "cpo", "roadmap", "features"]},
    "jorge":     {"emoji": "✍️", "color": "#F97316", "tags": ["contenido", "copywriting", "blog", "editorial"]},
    "lucia":     {"emoji": "🔍", "color": "#14B8A6", "tags": ["seo", "visibilidad", "analytics", "keywords"]},
    "isabella":  {"emoji": "📢", "color": "#8B5CF6", "tags": ["paid-media", "campañas", "ads", "performance"]},
    "mateo":     {"emoji": "📱", "color": "#3B82F6", "tags": ["social-media", "redes", "community", "brand-voice"]},
    "andres":    {"emoji": "📊", "color": "#6366F1", "tags": ["data", "analytics", "dashboards", "insights"]},
    "daniela":   {"emoji": "🛡️", "color": "#991B1B", "tags": ["inteligencia-competitiva", "research", "mercado"]},
    "emilio":    {"emoji": "🤝", "color": "#10B981", "tags": ["customer-success", "retención", "nps", "soporte"]},
    "patricia":  {"emoji": "⚖️", "color": "#B45309", "tags": ["legal", "compliance", "contratos", "regulación"]},
    "santiago":  {"emoji": "📈", "color": "#F59E0B", "tags": ["revenue-ops", "pipeline", "crm", "forecast"]},
    "catalina":  {"emoji": "📋", "color": "#EC4899", "tags": ["project-management", "okrs", "planning", "sprints"]},
    "shiftai":   {"emoji": "✨", "color": "#00A651", "tags": ["general", "orquestador", "multi-agente", "asistente"]},
}


def _load_system_prompt(agent_id: str) -> str:
    """Load the skill_prompt from the agent YAML file (READ-ONLY)."""
    filepath = os.path.join(SKILLS_DIR, f"{agent_id}.yaml")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("skill_prompt", "")
    except Exception:
        return ""


def _build_agent_entry(agent_id: str, info: dict) -> dict:
    """Build a single agent entry in LobeChat market schema."""
    meta = AGENT_META_OVERRIDES.get(agent_id, {})
    emoji = meta.get("emoji", "✨")
    tags = meta.get("tags", [])
    system_prompt = _load_system_prompt(agent_id)

    return {
        "author": "Shift Lab",
        "createdAt": "2026-04-20",
        "homepage": "https://shift.lat",
        "identifier": agent_id,
        "knowledgeCount": 0,
        "meta": {
            "avatar": emoji,
            "title": info.get("name", agent_id.capitalize()),
            "description": info.get("role", "Specialist"),
            "tags": tags,
            "category": "career",
        },
        "pluginCount": 0,
        "schemaVersion": 1,
        "tokenUsage": len(system_prompt.split()),
        "config": {
            "systemRole": system_prompt,
            "model": "cerebro-core",
            "params": {
                "temperature": 0.7,
            },
        },
    }


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@market_router.get("/agents.json")
async def agents_index():
    """Return all 15 Cerebro agents in LobeChat AGENTS_INDEX_URL format."""
    agents_list = [
        _build_agent_entry(agent_id, info)
        for agent_id, info in AGENTS.items()
    ]
    return JSONResponse(
        content={
            "schemaVersion": 1,
            "agents": agents_list,
        },
        headers={
            "Cache-Control": "public, max-age=60",
            "Access-Control-Allow-Origin": "*",
        },
    )


@market_router.get("/{identifier}.json")
async def agent_detail(identifier: str):
    """Return a single agent detail (LobeChat fetches this for the detail page)."""
    info = AGENTS.get(identifier)
    if not info:
        return JSONResponse(content={"error": "Agent not found"}, status_code=404)

    entry = _build_agent_entry(identifier, info)
    return JSONResponse(
        content=entry,
        headers={
            "Cache-Control": "public, max-age=60",
            "Access-Control-Allow-Origin": "*",
        },
    )
