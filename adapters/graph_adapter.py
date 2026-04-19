"""Graph Adapter — /graph/generate and /graph/execute endpoints.
Implements the Modo Nodos chat-first backend contract from the Redesign Plan.

/graph/generate — Shifty-Architect generates a DAG from user intent
/graph/execute  — Executes the DAG node-by-node, streaming progress via SSE
"""
import json
import time
import uuid
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from agents.registry import AGENTS
from config.models import get_llm
from config.database import get_db_connection
from graph.architect import generate_graph
from graph.nodes import create_agent_node_with_model
from graph.synthesizer import synthesizer_node
from graph.web_search import perform_web_search
from punto_medio import get_dynamic_rag
from tenant_constitution import get_tenant_context_with_fallback

graph_router = APIRouter(prefix="/graph", tags=["graph"])

# ═══════════════════════════════════════════════════════════════
# HITL — In-memory pause registry (single-worker, Railway)
# ═══════════════════════════════════════════════════════════════
# Key: pause_id → (asyncio.Event, holder dict with decision)
# Cleanup: finally block in SSE stream + 30 min timeout
_pause_events: Dict[str, Tuple[asyncio.Event, dict]] = {}

HITL_TIMEOUT_SECONDS = 1800  # 30 minutes


# ═══════════════════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════

class GraphGenerateRequest(BaseModel):
    """Request body for /graph/generate"""
    user_message: str
    current_graph: Optional[dict] = None
    chat_history: Optional[List[dict]] = None
    tenant_id: str = "shift"
    model: Optional[str] = "claude-sonnet-4-6"


class GraphExecuteRequest(BaseModel):
    """Request body for /graph/execute — receives the serialized graph"""
    graph: dict  # { nodes: [...], edges: [...] }
    tenant_id: str = "shift"
    model: Optional[str] = "Claude 3.5 Sonnet"
    session_id: Optional[str] = None
    user_metadata: Optional[dict] = None


class GraphResumeRequest(BaseModel):
    """Request body for /graph/resume — resumes a paused HITL node"""
    pause_id: str
    decision: str = "approve"  # "approve" | "reject"


# ═══════════════════════════════════════════════════════════════
# POST /graph/generate
# ═══════════════════════════════════════════════════════════════

@graph_router.post("/generate")
async def graph_generate(request: GraphGenerateRequest):
    """Shifty-Architect generates a DAG from natural language intent.
    
    Input:  { user_message, current_graph?, chat_history, tenant_id }
    Output: { mode, narrative?, graph?, explanation_per_node?, message? }
    """
    try:
        print(f"[GRAPH/GENERATE] tenant={request.tenant_id} | msg={request.user_message[:80]}...")
        
        result = await generate_graph(
            user_message=request.user_message,
            tenant_id=request.tenant_id,
            current_graph=request.current_graph,
            chat_history=request.chat_history,
            model=request.model or "claude-sonnet-4-6",
        )
        
        mode = result.get("mode", "chat")
        if mode == "graph":
            node_count = len(result.get("graph", {}).get("nodes", []))
            print(f"[GRAPH/GENERATE] ✓ Graph with {node_count} nodes")
        else:
            print(f"[GRAPH/GENERATE] ✓ Chat response")
        
        return result
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Architect error: {str(e)}")


# ═══════════════════════════════════════════════════════════════
# POST /graph/execute  (SSE Streaming)
# ═══════════════════════════════════════════════════════════════

@graph_router.post("/execute")
async def graph_execute(request: GraphExecuteRequest, background_tasks: BackgroundTasks):
    """Execute a graph node-by-node, streaming progress via SSE.
    
    Each SSE event is a JSON with:
      { "event": "node_start"|"node_complete"|"synthesis"|"delivery"|"done"|"error",
        "node_id": "...",
        "agent_name": "...",
        "content": "...",    (agent output, partial or complete)
        "progress": 0.0-1.0  (overall progress)
      }
    """
    graph = request.graph
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    tenant_id = request.tenant_id
    model = request.model or "Claude 3.5 Sonnet"
    
    if not nodes:
        raise HTTPException(status_code=400, detail="Graph has no nodes")
    
    async def sse_stream():
        """Generator that yields SSE events as the graph executes."""
        try:
            # Topological sort
            execution_order = _topo_sort(nodes, edges)
            total_steps = len(execution_order)
            
            # Context accumulator
            context_text = ""
            agent_outputs: Dict[str, str] = {}
            all_messages: list = []
            
            for step_idx, node in enumerate(execution_order):
                node_id = node.get("id", "unknown")
                node_type = node.get("type", "unknown")
                node_data = node.get("data", {})
                progress = (step_idx + 1) / total_steps
                
                # ═══ CONTEXTO NODE ═══
                if node_type == "contexto":
                    context_text = node_data.get("text", "")
                    toggles = node_data.get("toggles", {})
                    
                    # Web search toggle
                    if toggles.get("web"):
                        yield _sse_event("node_start", node_id, "Buscando en web...", progress, agent_name="Sistema")
                        search_results = await perform_web_search(context_text)
                        context_text += f"\n\n[WEB SEARCH]:\n{search_results}"
                    
                    # BrandHub toggle
                    brandhub = toggles.get("brandhub")
                    if brandhub:
                        try:
                            conn = get_db_connection()
                            rag = get_dynamic_rag(conn, tenant_id)
                            context_text += f"\n\n[BRANDHUB {brandhub}]:\n{rag['combined_rag']}"
                            if conn: conn.close()
                        except Exception as rag_err:
                            print(f"[EXECUTE] BrandHub error: {rag_err}")
                    
                    yield _sse_event("node_complete", node_id, "Contexto preparado", progress, agent_name="Contexto")
                
                # ═══ AGENTE NODE ═══
                elif node_type == "agente":
                    agent_id = node_data.get("agent_id", "shiftai")
                    addendum = node_data.get("addendum", "")
                    agent_name = AGENTS.get(agent_id, {}).get("name", agent_id)
                    model_override = node_data.get("model_override") or model
                    
                    yield _sse_event("node_start", node_id, f"{agent_name} trabajando...", progress, agent_name=agent_name)
                    
                    # Build messages for this agent
                    agent_messages = [HumanMessage(content=f"{context_text}\n\n{addendum}")]
                    
                    # Include prior agent outputs as context
                    for prev_id, prev_output in agent_outputs.items():
                        prev_name = AGENTS.get(prev_id, {}).get("name", prev_id)
                        agent_messages.insert(0, AIMessage(content=f"[{prev_name}]: {prev_output}"))
                    
                    # Execute agent
                    try:
                        from graph.nodes import create_async_agent_node
                        agent_fn = create_async_agent_node(agent_id, model_override, tenant_id)
                        state = {
                            "messages": agent_messages,
                            "context": context_text,
                            "active_agent": agent_id,
                            "agent_outputs": agent_outputs,
                        }
                        result = await agent_fn(state)
                        
                        # Extract output
                        result_messages = result.get("messages", [])
                        agent_output = ""
                        if result_messages:
                            last = result_messages[-1]
                            agent_output = last.content if hasattr(last, 'content') else str(last)
                        
                        agent_outputs[agent_id] = agent_output
                        
                        yield _sse_event("node_complete", node_id, agent_output, progress, agent_name=agent_name)
                        
                    except Exception as agent_err:
                        yield _sse_event("error", node_id, f"Error: {str(agent_err)}", progress, agent_name=agent_name)
                
                # ═══ REVISION (HITL) NODE — REAL PAUSE ═══
                elif node_type == "revision":
                    prompt = node_data.get("prompt", "Revisa antes de continuar")
                    pause_id = str(uuid.uuid4())
                    event = asyncio.Event()
                    holder: dict = {}
                    _pause_events[pause_id] = (event, holder)
                    
                    yield _sse_event("hitl_pause", node_id, prompt, progress, agent_name="Revisión Humana", pause_id=pause_id)
                    print(f"[EXECUTE] HITL pause: {pause_id} — waiting for /graph/resume")
                    
                    try:
                        await asyncio.wait_for(event.wait(), timeout=HITL_TIMEOUT_SECONDS)
                        decision = holder.get("decision", "approve")
                        print(f"[EXECUTE] HITL resumed: {pause_id} → {decision}")
                        
                        if decision == "reject":
                            yield _sse_event("hitl_rejected", node_id, "Ejecución cancelada por el usuario", progress, agent_name="Revisión Humana")
                            yield _sse_event("done", "graph", json.dumps({
                                "agents_executed": list(agent_outputs.keys()),
                                "total_nodes": total_steps,
                                "cancelled_at": node_id,
                                "reason": "hitl_rejected",
                            }), progress, agent_name="Cancelado")
                            return  # Stop the stream
                        
                        yield _sse_event("hitl_approved", node_id, "Aprobado — continuando", progress, agent_name="Revisión Humana")
                        
                    except asyncio.TimeoutError:
                        yield _sse_event("hitl_timeout", node_id, "Revisión abandonada (timeout 30 min)", progress, agent_name="Revisión Humana")
                        yield _sse_event("done", "graph", json.dumps({
                            "agents_executed": list(agent_outputs.keys()),
                            "total_nodes": total_steps,
                            "cancelled_at": node_id,
                            "reason": "hitl_timeout",
                        }), progress, agent_name="Timeout")
                        return  # Stop the stream
                    finally:
                        _pause_events.pop(pause_id, None)
                
                # ═══ ENTREGA NODE ═══
                elif node_type == "entrega":
                    fmt = node_data.get("format", "text")
                    destination = node_data.get("destination", "chat")
                    
                    yield _sse_event("node_start", node_id, f"Preparando entrega ({fmt})...", progress, agent_name="Entrega")
                    
                    # Check if multi-agent synthesis needed
                    if len(agent_outputs) > 1:
                        yield _sse_event("synthesis", node_id, "Consolidando perspectivas...", progress, agent_name="Synthesizer")
                        
                        # Run synthesizer
                        synth_state = {
                            "messages": [HumanMessage(content=context_text)],
                            "agent_outputs": agent_outputs,
                            "model_name": model,
                            "context": context_text,
                            "active_agent": "synthesizer",
                        }
                        synth_result = await synthesizer_node(synth_state)
                        synth_messages = synth_result.get("messages", synth_state["messages"])
                        final_content = synth_messages[-1].content if synth_messages else ""
                    else:
                        # Single agent — use its output directly
                        final_content = list(agent_outputs.values())[0] if agent_outputs else ""
                    
                    # Format conversion
                    delivery_url = None
                    if fmt != "text" and final_content:
                        delivery_url = await _generate_document(fmt, final_content, tenant_id)
                    
                    delivery_payload = {
                        "format": fmt,
                        "destination": destination,
                        "content": final_content,
                        "document_url": delivery_url,
                    }
                    
                    yield _sse_event("delivery", node_id, json.dumps(delivery_payload), 1.0, agent_name="Entrega")
                
                # Small delay between nodes for streaming feel
                await asyncio.sleep(0.2)
            
            # ═══ AUTO-INGEST ═══
            safe_session = request.session_id or f"graph_{int(time.time())}"
            all_agent_ids = list(agent_outputs.keys())
            combined_output = "\n\n---\n\n".join(
                f"[{AGENTS.get(aid, {}).get('name', aid)}]: {out}" 
                for aid, out in agent_outputs.items()
            )
            # Ingest in background
            try:
                conn = get_db_connection()
                if conn:
                    conn.close()
            except Exception:
                pass
            
            yield _sse_event("done", "graph", json.dumps({
                "agents_executed": all_agent_ids,
                "total_nodes": total_steps,
            }), 1.0, agent_name="Completado")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield _sse_event("error", "graph", str(e), 0.0, agent_name="Error")
    
    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ═══════════════════════════════════════════════════════════════
# POST /graph/resume  (HITL approve/reject)
# ═══════════════════════════════════════════════════════════════

@graph_router.post("/resume")
async def graph_resume(request: GraphResumeRequest):
    """Resume a paused graph execution after HITL review.
    
    The frontend receives a `pause_id` in the `hitl_pause` SSE event,
    then POSTs here with the decision to unblock the stream.
    """
    entry = _pause_events.get(request.pause_id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"Pause '{request.pause_id}' not found — may have timed out or already resumed"
        )
    
    event, holder = entry
    holder["decision"] = request.decision
    event.set()
    
    print(f"[GRAPH/RESUME] {request.pause_id} → {request.decision}")
    return {"status": "resumed", "decision": request.decision}


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def _sse_event(event: str, node_id: str, content: str, progress: float, agent_name: str = "", pause_id: Optional[str] = None) -> str:
    """Format an SSE event as a string."""
    payload = {
        "event": event,
        "node_id": node_id,
        "agent_name": agent_name,
        "content": content,
        "progress": round(progress, 2),
        "timestamp": time.time(),
    }
    if pause_id:
        payload["pause_id"] = pause_id
    data = json.dumps(payload, ensure_ascii=False)
    return f"data: {data}\n\n"


def _topo_sort(nodes: list, edges: list) -> list:
    """Topological sort of graph nodes for execution order.
    Parallel nodes (fan-out) are kept adjacent in the order."""
    
    node_map = {n["id"]: n for n in nodes}
    in_degree = {n["id"]: 0 for n in nodes}
    adj: Dict[str, list] = {n["id"]: [] for n in nodes}
    
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src in adj and tgt in in_degree:
            adj[src].append(tgt)
            in_degree[tgt] += 1
    
    # Kahn's algorithm
    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    result = []
    
    while queue:
        # Sort for deterministic order
        queue.sort()
        node_id = queue.pop(0)
        result.append(node_map[node_id])
        
        for neighbor in adj.get(node_id, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    
    if len(result) != len(nodes):
        # Cycle detected or disconnected nodes — append remaining
        remaining = [n for n in nodes if n["id"] not in {r["id"] for r in result}]
        result.extend(remaining)
    
    return result


async def _generate_document(fmt: str, content: str, tenant_id: str) -> Optional[str]:
    """Generate a document in the specified format using existing tools."""
    try:
        if fmt == "docx":
            from tools.document_tools import create_word_document
            result = create_word_document.func(
                title=f"Entrega — {tenant_id.upper()}",
                content=content,
                author="Shifty Studio"
            )
            return result
        
        elif fmt == "pdf":
            from tools.extended_tools import generate_pdf_report
            result = generate_pdf_report.func(
                title=f"Reporte — {tenant_id.upper()}",
                content=content,
                report_type="general"
            )
            return result
        
        elif fmt == "pptx":
            from tools.extended_tools import create_presentation
            result = create_presentation.func(
                title=f"Presentación — {tenant_id.upper()}",
                slides_content=[{"title": "Contenido", "content": content}]
            )
            return result
        
        elif fmt == "xlsx":
            # Basic text-in-cell export via CSV-like approach
            # Full xlsx generation would need openpyxl (v2)
            return None
        
        return None
    except Exception as e:
        print(f"[EXECUTE] Document generation error: {e}")
        return None
