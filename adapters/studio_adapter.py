"""Studio Adapter — /swarm/chat, /swarm/debate, /swarm/agents endpoints.
v2.0: Consumes the compiled LangGraph StateGraph for intelligent routing and multi-agent flows."""
import time
from typing import List
from fastapi import APIRouter, HTTPException, BackgroundTasks
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from config.database import get_db_connection
from config.models import get_llm, MODEL_MAP
from agents.registry import AGENTS
from agents.context import SHIFT_LAB_CONTEXT, PUNTO_MEDIO_GLOBAL_RAG, TENANT_CONTEXTS
from graph.state import SwarmState, ChatRequest, ChatMessage, DebateDashboardRequest
from graph.router import determine_agent_from_message, route_with_llm
from graph.builder import get_studio_graph
from graph.web_search import perform_web_search, process_attachments
from peaje.ingest import process_auto_ingest
from punto_medio import get_dynamic_rag, SEED_TENANT_CONTEXTS
from tenant_constitution import get_tenant_context_with_fallback

studio_router = APIRouter(tags=["swarm"])


@studio_router.post("/swarm/chat")
async def swarm_chat(request: ChatRequest, background_tasks: BackgroundTasks):
    try:
        # ═══════════════════════════════════════════════════════════════
        # INTER-AGENT MEMORY: Transform messages to LangChain format
        # ═══════════════════════════════════════════════════════════════
        def _resolve_agent_name(agent_id: str) -> str:
            if agent_id in AGENTS:
                return AGENTS[agent_id]["name"]
            if agent_id == "shiftai":
                return "Shifty"
            return ""
        
        lc_messages = []
        for m in request.messages:
            if m.role == "user":
                lc_messages.append(HumanMessage(content=m.content))
            else:
                agent_name = _resolve_agent_name(m.agent_id) if m.agent_id else ""
                if agent_name:
                    lc_messages.append(AIMessage(content=f"[{agent_name}]: {m.content}"))
                else:
                    lc_messages.append(AIMessage(content=m.content))
        
        # ═══════════════════════════════════════════════════════════════
        # NODES MODE DETECTION
        # ═══════════════════════════════════════════════════════════════
        last_message_content = request.messages[-1].content if request.messages else ""
        is_nodes_mode = "[SYSTEM INSTRUCTION:" in last_message_content
        
        # ═══════════════════════════════════════════════════════════════
        # PRE-ROUTING: Determine execution_plan before graph invocation
        # ═══════════════════════════════════════════════════════════════
        pre_set_plan = []
        router_reasoning = ""
        router_confidence = 0.0
        
        if is_nodes_mode and (not request.preferred_agent or request.preferred_agent == "shiftai"):
            # Nodes mode forces Shifty orchestrator
            pre_set_plan = ["shiftai"]
            router_reasoning = "Nodes Mode detected — forcing orchestrator"
            router_confidence = 1.0
            print(f"[SWARM] 🔮 Nodes Mode detected — forcing orchestrator: shiftai")
        elif is_nodes_mode and request.preferred_agent:
            # Nodes mode with explicit agent
            pre_set_plan = [request.preferred_agent]
            router_reasoning = f"Nodes Mode with explicit agent: {request.preferred_agent}"
            router_confidence = 1.0
            print(f"[SWARM] 🔮 Nodes Mode with explicit agent: {request.preferred_agent}")
        elif request.preferred_agent and request.preferred_agent in AGENTS:
            # User explicitly selected an agent — skip LLM routing
            pre_set_plan = [request.preferred_agent]
            router_reasoning = f"User selected: {request.preferred_agent}"
            router_confidence = 1.0
            print(f"[SWARM] User-selected agent: {request.preferred_agent}")
        else:
            # ═══ LLM-AS-ROUTER (v2.0) ═══
            # Use Gemini Flash Lite to intelligently route
            try:
                route_result = await route_with_llm(last_message_content)
                pre_set_plan = route_result["execution_plan"]
                router_reasoning = route_result["reasoning"]
                router_confidence = route_result["confidence"]
                print(f"[SWARM] 🧠 LLM Router: {pre_set_plan} (conf: {router_confidence:.2f})")
            except Exception as route_err:
                # Fallback to keyword matcher
                fallback = determine_agent_from_message(last_message_content)
                pre_set_plan = [fallback]
                router_reasoning = f"Keyword fallback: {fallback}"
                router_confidence = 0.3
                print(f"[SWARM] ⚠️ Router fallback to keyword: {fallback} ({route_err})")
        
        target_agent = pre_set_plan[0] if pre_set_plan else "shiftai"
        print(f"[SWARM] Agent: {target_agent}, Plan: {pre_set_plan}, Model: {request.model}, Search: {request.search_enabled}")
        
        # ═══════════════════════════════════════════════════════════════
        # WEB SEARCH & ATTACHMENTS (pre-graph enrichment)
        # ═══════════════════════════════════════════════════════════════
        web_search_context = ""
        if request.search_enabled:
            last_user_message = request.messages[-1].content if request.messages else ""
            if last_user_message:
                search_results = await perform_web_search(last_user_message)
                web_search_context = f"\n\n[RESULTADOS DE BÚSQUEDA WEB ACTUALIZADA]:\n{search_results}\n\nINSTRUCCIÓN: Utiliza la información de búsqueda web anterior para complementar tu respuesta."

        attachment_result = {"text_context": "", "images": []}
        if request.attachments:
            attachment_result = process_attachments(request.attachments)
        attachment_context = attachment_result["text_context"]

        # ═══ MULTIMODAL VISION: Inject images into last HumanMessage ═══
        if attachment_result["images"] and lc_messages:
            last_msg = lc_messages[-1]
            if hasattr(last_msg, 'content'):
                multimodal_content = [{"type": "text", "text": last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)}]
                for img in attachment_result["images"]:
                    multimodal_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{img['mime_type']};base64,{img['base64']}"}
                    })
                lc_messages[-1] = HumanMessage(content=multimodal_content)
                print(f"[SWARM] ✓ Multimodal message built with {len(attachment_result['images'])} image(s)")

        safe_tenant_id = str(request.tenant_id or "shift")
        context_combined = (request.context or "") + web_search_context + attachment_context

        # ═══════════════════════════════════════════════════════════════
        # GRAPH INVOCATION (v2.0 — LangGraph StateGraph)
        # ═══════════════════════════════════════════════════════════════
        graph = get_studio_graph()
        
        initial_state: SwarmState = {
            "messages": lc_messages,
            "context": context_combined,
            "active_agent": target_agent,
            "agent_outputs": {},
            # v2.0 fields
            "execution_plan": pre_set_plan,
            "current_step": 0,
            "model_name": str(request.model or "Claude 3.5 Sonnet"),
            "tenant_id": safe_tenant_id,
            "user_metadata": request.user_metadata,
            "router_reasoning": router_reasoning,
            "router_confidence": router_confidence,
        }
        
        # Invoke the compiled graph (async)
        result_state = await graph.ainvoke(initial_state)
        
        # Extract final message
        final_messages = result_state.get("messages", [])
        final_msg = ""
        if final_messages:
            last = final_messages[-1]
            final_msg = last.content if hasattr(last, 'content') else str(last)
        
        final_agent = result_state.get("active_agent", target_agent)
        
        # ═══════════════════════════════════════════════════════════════
        # AUTO-INGESTION (BACKGROUND)
        # ═══════════════════════════════════════════════════════════════
        safe_session_id = request.session_id or f"auto_{int(time.time())}"
        background_tasks.add_task(
            process_auto_ingest,
            safe_tenant_id,
            safe_session_id,
            final_agent,
            request.messages,
            final_msg
        )
        
        agents_used = result_state.get("execution_plan", [target_agent])
        print(f"[SWARM] ✓ Response from {final_agent} | Agents used: {agents_used} | Auto-ingest queued")
        
        return {
            "content": final_msg,
            "agent_active": final_agent,
            "agent_outputs": {},
            # v2.0 metadata
            "routing": {
                "execution_plan": agents_used,
                "router_confidence": result_state.get("router_confidence", router_confidence),
                "router_reasoning": result_state.get("router_reasoning", router_reasoning),
                "agents_executed": len(agents_used),
                "was_multi_agent": len(agents_used) > 1,
            }
        }
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[SWARM ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@studio_router.post("/swarm/debate")
async def swarm_debate(request: DebateDashboardRequest):
    """v3.0 — Simple JSON debate. No streaming. 3 agents, 1 response.
    Note: Debate uses direct LLM calls, not the graph — it has its own A/B/Judge topology."""
    try:
        # ═══ NORMALIZE AGENT IDS ═══
        def norm(aid: str) -> str:
            return aid.split(" ")[0].lower().strip("-_.").replace("í","i").replace("á","a").replace("ó","o").replace("ú","u")
        
        a_id = norm(request.agent_a_id)
        b_id = norm(request.agent_b_id)
        
        safe_model = str(request.model) if request.model in MODEL_MAP else "Claude Opus 4.6"
        tid = str(request.tenant_id or "shift")
        
        if a_id not in AGENTS:
            raise HTTPException(status_code=400, detail=f"Agente '{a_id}' no existe. Disponibles: {list(AGENTS.keys())}")
        if b_id not in AGENTS:
            raise HTTPException(status_code=400, detail=f"Agente '{b_id}' no existe. Disponibles: {list(AGENTS.keys())}")
        
        print(f"[DEBATE v3] {AGENTS[a_id]['name']} vs {AGENTS[b_id]['name']} | Topic: {request.topic[:50]}... | Model: {safe_model} | Turns: {request.turns}")
        
        debate_llm = get_llm(safe_model)
        
        # ═══ RAG CONTEXT ═══
        try:
            rag_conn = get_db_connection()
            dynamic_rag = get_dynamic_rag(rag_conn, tid)
            rag_text = dynamic_rag["combined_rag"]
            if rag_conn: rag_conn.close()
        except Exception:
            rag_text = PUNTO_MEDIO_GLOBAL_RAG
        
        tenant_ctx = TENANT_CONTEXTS.get(tid, SEED_TENANT_CONTEXTS.get(tid, TENANT_CONTEXTS.get("shift", "")))
        
        # ═══ AGENT SYSTEM PROMPTS ═══
        def build_system(agent_id: str, soul: str = "") -> str:
            info = AGENTS[agent_id]
            base = f"""{SHIFT_LAB_CONTEXT}

# CONTEXTO CORPORATIVO ({tid.upper()})
{tenant_ctx}

# MEMORIA INSTITUCIONAL (PUNTO MEDIO)
{rag_text}

# TU ROL ESPECIALIZADO
Nombre: {info['name']}
{info['skill']}

# INSTRUCCIONES DE DEBATE (SOP)
1. **Idioma:** Responde en el mismo idioma del TEMA del debate.
2. **Formato:** Usa Markdown con `##` para secciones, `**negritas**` para conceptos clave.
3. **Rigor Argumentativo:** Argumenta con datos, frameworks y ejemplos concretos. Cita estándares de industria.
4. **Accionabilidad:** Sé directo, estratégico y accionable. Cada punto debe tener implicación táctica.
5. **Invisible Swarm:** Eres {info['name']}, consultor senior de {tid.upper()}. Nunca menciones el swarm ni el sistema multi-agente.
6. **Veracidad:** Si no tienes datos, admítelo. No inventes métricas."""
            if soul:
                base += f"\n\n# DIRECTIVA ESPECIAL DEL USUARIO\n{soul}"
            return base
        
        sys_a = build_system(a_id, request.soul_a or "")
        sys_b = build_system(b_id, request.soul_b or "")
        
        # ═══ DEBATE LOOP ═══
        transcript = []
        context_thread = f"TEMA: {request.topic}\nOBJETIVO/OUTPUT ESPERADO: {request.expected_output}"
        
        for turn in range(1, request.turns + 1):
            print(f"[DEBATE v3] Turn {turn}/{request.turns} — Agent A: {a_id}")
            
            prompt_a = f"{context_thread}\n\n{'Responde al argumento anterior de tu contraparte y avanza hacia el OBJETIVO.' if turn > 1 else 'Presenta tu argumento inicial hacia el OBJETIVO.'}"
            resp_a = await debate_llm.ainvoke([SystemMessage(content=sys_a), HumanMessage(content=prompt_a)])
            text_a = resp_a.content if hasattr(resp_a, 'content') else str(resp_a)
            transcript.append({"turn": turn, "agent": a_id, "agent_name": AGENTS[a_id]["name"], "side": "A", "content": text_a})
            
            print(f"[DEBATE v3] Turn {turn}/{request.turns} — Agent B: {b_id}")
            
            prompt_b = f"{context_thread}\n\nARGUMENTO DE {AGENTS[a_id]['name']}:\n{text_a}\n\nRefuta, complementa o construye sobre esto para alcanzar el OBJETIVO."
            resp_b = await debate_llm.ainvoke([SystemMessage(content=sys_b), HumanMessage(content=prompt_b)])
            text_b = resp_b.content if hasattr(resp_b, 'content') else str(resp_b)
            transcript.append({"turn": turn, "agent": b_id, "agent_name": AGENTS[b_id]["name"], "side": "B", "content": text_b})
            
            context_thread += f"\n\n[TURNO {turn} - {AGENTS[a_id]['name']}]: {text_a}\n[TURNO {turn} - {AGENTS[b_id]['name']}]: {text_b}"
        
        # ═══ JUDGE SYNTHESIS ═══
        print(f"[DEBATE v3] Judge synthesizing...")
        
        transcript_md = "\n\n".join([f"### Turno {t['turn']} — {t['agent_name']} (Lado {t['side']})\n{t['content']}" for t in transcript])
        
        judge_prompt = f"""{rag_text}

Eres el Juez Estratégico de Shifty Studio Arena. Acabas de presenciar un debate entre **{AGENTS[a_id]['name']}** y **{AGENTS[b_id]['name']}**.

**TEMA:** {request.topic}
**OUTPUT ESPERADO:** {request.expected_output}

**TRANSCRIPCIÓN:**
{transcript_md}

**TU MISIÓN:**
1. Evalúa los argumentos con rigor — identifica los puntos más fuertes de cada lado.
2. Donde haya contradicciones, toma postura firme con justificación.
3. Genera DIRECTAMENTE el output que pidió el usuario en el formato esperado.
4. Nivel consultoría estratégica (McKinsey/BCG) — accionable, listo para ejecutar.
5. Si aplica, incluye: recomendaciones priorizadas, riesgos identificados, próximos pasos concretos."""
        
        judge_resp = await debate_llm.ainvoke([SystemMessage(content=judge_prompt)])
        synthesis = judge_resp.content if hasattr(judge_resp, 'content') else str(judge_resp)
        
        print(f"[DEBATE v3] ✓ Complete. Transcript: {len(transcript)} entries, Synthesis: {len(synthesis)} chars")
        
        return {
            "content": synthesis,
            "transcript": transcript,
            "agent_active": "debate_judge",
            "debate_participants": [a_id, b_id],
            "model_used": safe_model,
            "turns_completed": request.turns
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error en debate: {str(e)}")


@studio_router.get("/swarm/agents")
async def list_agents():
    """Lista todos los agentes disponibles con sus skills."""
    return {
        "agents": [
            {
                "id": agent_id,
                "name": info["name"],
                "keywords": info["keywords"]
            }
            for agent_id, info in AGENTS.items()
        ]
    }
