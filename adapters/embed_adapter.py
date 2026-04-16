"""Embed Adapter — Lightweight copilot API for embedding CEREBRO in external tools.
Exposes a subset of agents and a simplified API surface for corporate tool integration.

Usage: Grupo Garnier admin tools, HR platforms, analytics dashboards, etc.
Each embed instance declares which agents and capabilities it needs."""
import time
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage

from config.database import get_db_connection
from agents.registry import AGENTS
from graph.state import SwarmState, ChatMessage
from graph.router import route_with_llm, determine_agent_from_message
from graph.builder import get_embed_graph
from graph.web_search import perform_web_search
from peaje.ingest import process_auto_ingest
from punto_medio import get_dynamic_rag


embed_router = APIRouter(prefix="/embed", tags=["embed"])


# ═══════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════

class EmbedChatRequest(BaseModel):
    """Simplified chat request for embedded copilots."""
    messages: List[ChatMessage]
    tenant_id: str = "shift"
    session_id: Optional[str] = None
    model: Optional[str] = "Claude 3.5 Sonnet"
    search_enabled: Optional[bool] = False
    # Embed-specific: declare which agents this copilot can access
    active_agents: Optional[List[str]] = None
    # Embed-specific: context about the host tool
    host_context: Optional[str] = None
    user_metadata: Optional[dict] = None


class EmbedConfigResponse(BaseModel):
    """Returns the config of available agents for this embed instance."""
    available_agents: List[Dict]
    tenant_id: str
    version: str


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@embed_router.post("/chat")
async def embed_chat(request: EmbedChatRequest, background_tasks: BackgroundTasks):
    """Lightweight chat endpoint for embedded copilots.
    Only activates the agents declared in active_agents.
    If no agents specified, defaults to [shiftai, roberto, patricia]."""
    try:
        # Default agent subset for generic embeds
        active_agents = request.active_agents or ["shiftai", "roberto", "patricia"]
        # Validate agents exist
        active_agents = [a for a in active_agents if a in AGENTS]
        if not active_agents:
            active_agents = ["shiftai"]
        
        # Transform messages
        lc_messages = []
        for m in request.messages:
            if m.role == "user":
                lc_messages.append(HumanMessage(content=m.content))
            else:
                lc_messages.append(AIMessage(content=m.content))
        
        last_message = request.messages[-1].content if request.messages else ""
        safe_tenant_id = str(request.tenant_id or "shift")
        
        # Route using LLM (will only select from active_agents)
        try:
            route_result = await route_with_llm(last_message)
            # Constrain to active agents
            agent_id = route_result["agent_id"]
            if agent_id not in active_agents:
                agent_id = active_agents[0]
            plan = [a for a in route_result["execution_plan"] if a in active_agents]
            if not plan:
                plan = [agent_id]
            router_reasoning = route_result["reasoning"]
            router_confidence = route_result["confidence"]
        except Exception:
            agent_id = determine_agent_from_message(last_message)
            if agent_id not in active_agents:
                agent_id = active_agents[0]
            plan = [agent_id]
            router_reasoning = f"Fallback: {agent_id}"
            router_confidence = 0.3
        
        # Web search (optional)
        web_context = ""
        if request.search_enabled and last_message:
            search_results = await perform_web_search(last_message)
            web_context = f"\n\n[WEB SEARCH]:\n{search_results}"
        
        # Host context injection
        host_ctx = ""
        if request.host_context:
            host_ctx = f"\n\n[HOST TOOL CONTEXT]:\n{request.host_context}\nINSTRUCCIÓN: Adapta tu respuesta al contexto de la herramienta donde estás embebido."
        
        context_combined = web_context + host_ctx
        
        # Build and invoke the embed graph
        graph = get_embed_graph(active_agents=active_agents)
        
        initial_state: SwarmState = {
            "messages": lc_messages,
            "context": context_combined,
            "active_agent": agent_id,
            "agent_outputs": {},
            "execution_plan": plan,
            "current_step": 0,
            "model_name": str(request.model or "Claude 3.5 Sonnet"),
            "tenant_id": safe_tenant_id,
            "user_metadata": request.user_metadata,
            "router_reasoning": router_reasoning,
            "router_confidence": router_confidence,
        }
        
        result_state = await graph.ainvoke(initial_state)
        
        # Extract response
        final_messages = result_state.get("messages", [])
        final_msg = ""
        if final_messages:
            last = final_messages[-1]
            final_msg = last.content if hasattr(last, 'content') else str(last)
        
        final_agent = result_state.get("active_agent", agent_id)
        
        # Auto-ingest
        safe_session_id = request.session_id or f"embed_{int(time.time())}"
        background_tasks.add_task(
            process_auto_ingest,
            safe_tenant_id,
            safe_session_id,
            final_agent,
            request.messages,
            final_msg
        )
        
        print(f"[EMBED] ✓ Response from {final_agent} | Active agents: {active_agents}")
        
        return {
            "content": final_msg,
            "agent_active": final_agent,
            "routing": {
                "execution_plan": plan,
                "available_agents": active_agents,
                "router_confidence": router_confidence,
            }
        }
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@embed_router.get("/config")
async def embed_config(tenant_id: str = "shift", agents: Optional[str] = None):
    """Get configuration for an embed instance.
    Query param `agents` is a comma-separated list of agent IDs to include."""
    
    if agents:
        active_ids = [a.strip() for a in agents.split(",")]
        active_ids = [a for a in active_ids if a in AGENTS]
    else:
        active_ids = list(AGENTS.keys())
    
    return {
        "available_agents": [
            {
                "id": aid,
                "name": AGENTS[aid]["name"],
                "role": AGENTS[aid]["role"],
                "keywords": AGENTS[aid]["keywords"],
            }
            for aid in active_ids
        ],
        "tenant_id": tenant_id,
        "version": "v2.1.0-embed",
    }
