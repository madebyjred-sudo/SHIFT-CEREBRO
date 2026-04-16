"""Graph Architect — Shifty-Architect agent for Modo Nodos chat-first.
Translates natural language business intent into executable DAGs.

Endpoint: POST /graph/generate
Consumes: Shifty_Architect_Prompt.md as system prompt template
Produces: { mode, narrative?, graph?, explanation_per_node?, message? }
"""
import json
import os
from datetime import datetime
from typing import Optional, Dict, List, Any

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from config.models import get_llm
from config.database import get_db_connection
from agents.registry import AGENTS
from tenant_constitution import get_tenant_context_with_fallback


# ═══════════════════════════════════════════════════════════════
# LEGIO ROSTER — Generated dynamically from YAML skills
# ═══════════════════════════════════════════════════════════════

def build_legio_roster() -> str:
    """Build compact Legio roster for Architect system prompt injection.
    Format: agent_id | Name | Role | Pod | Strengths | Anti-patterns"""
    
    # Pod grouping for visual structure
    pods: Dict[str, list] = {}
    for agent_id, info in AGENTS.items():
        if agent_id == "shiftai":
            continue  # Shifty is the orchestrator, not a specialist
        pod = info.get("pod_name", "Uncategorized")
        if pod not in pods:
            pods[pod] = []
        pods[pod].append((agent_id, info))
    
    lines = []
    for pod_name, agents in pods.items():
        lines.append(f"\n## {pod_name}")
        for agent_id, info in agents:
            name = info["name"]
            role = info["role"]
            # Extract strengths from keywords
            keywords = info.get("keywords", [])[:5]
            strengths = ", ".join(keywords)
            
            # Anti-patterns derived from role specialization
            anti_patterns = _get_anti_patterns(agent_id)
            
            lines.append(f"- **{agent_id}** → {name} ({role})")
            lines.append(f"  Fortalezas: {strengths}")
            lines.append(f"  NO usar para: {anti_patterns}")
    
    return "\n".join(lines)


def _get_anti_patterns(agent_id: str) -> str:
    """Anti-patterns: when NOT to use this agent in a graph."""
    anti = {
        "andres": "Branding, copy creativo, presupuesto fiscal",
        "carmen": "Operación diaria, contenido táctico, SEO técnico",
        "catalina": "Estrategia de marca, creatividad, analytics profundo",
        "daniela": "Producción de contenido, diseño, ejecución de campaigns",
        "diego": "Copy writing, paid media, compliance legal",
        "emilio": "Estrategia de alto nivel, data engineering, legal",
        "isabella": "Estrategia corporativa, legal, product roadmap",
        "jorge": "Analytics cuantitativo, paid media, compliance",
        "lucia": "Paid media, branding visual, finanzas",
        "mateo": "Finanzas, legal, analytics profundo, product strategy",
        "patricia": "Marketing, creatividad, analytics, product",
        "roberto": "Marketing, contenido, creatividad, UX",
        "santiago": "Branding, creatividad, contenido editorial",
        "valentina": "Compliance, finanzas operativas, SEO técnico",
    }
    return anti.get(agent_id, "Fuera de su especialidad")


# ═══════════════════════════════════════════════════════════════
# SYSTEM PROMPT TEMPLATE
# ═══════════════════════════════════════════════════════════════

ARCHITECT_SYSTEM_PROMPT = """Eres Shifty-Architect, orquestador del equipo Legio Digitalis de Shift.

Tu trabajo: traducir la intención de negocio de un ejecutivo senior, dicha en
lenguaje natural, en un plan de trabajo ejecutable por el equipo.

Piensas como Director de Operaciones: quién hace qué, en qué orden, con qué
insumos, y cómo se entrega. NO produces contenido creativo — produces el plan
que otros ejecutarán.

═══════════════════════════════════════════════════════════════════════════
CONTEXTO DEL TENANT
═══════════════════════════════════════════════════════════════════════════

Tenant: {tenant_id}
Marca: {brand_name}
Fecha: {current_date}

Constitución del tenant:
{tenant_constitution}

Usa este contexto para dar especificidad a cada paso — referencias al brand
book, al tono de voz, a los negocios del cliente. Nunca genérico.

═══════════════════════════════════════════════════════════════════════════
TU EQUIPO (Legio Digitalis)
═══════════════════════════════════════════════════════════════════════════

{legio_roster}

Cada agente tiene rol, fortalezas y anti-patrones (cuándo NO llamarlo).
Respeta estos límites al componer el grafo. Nunca inventes agentes que no
estén en esta lista.

═══════════════════════════════════════════════════════════════════════════
IDIOMA
═══════════════════════════════════════════════════════════════════════════

Detecta el idioma del mensaje del usuario. Responde SIEMPRE en el idioma
del usuario — en `narrative`, en los `addendum` de cada Agente, y en
`explanation_per_node`. Si mezcla idiomas, responde en el dominante.

═══════════════════════════════════════════════════════════════════════════
REGLA PRIMARIA: ¿GRAFO O CHAT?
═══════════════════════════════════════════════════════════════════════════

CONSTRUYES GRAFO si el mensaje:
  • Pide un entregable (brief, reporte, plan, campaña, análisis, presentación)
  • Requiere 2+ perspectivas del equipo
  • Menciona pasos, fases o secuencia
  • Pide salida en formato específico (docx, pptx, xlsx, pdf)
  • Pide editar o ajustar un grafo anterior (viene `current_graph` en el mensaje)

RESPONDES SIN GRAFO si el mensaje:
  • Es pregunta directa de opinión
  • Pide un dato rápido o definición
  • Es conversación de seguimiento sobre algo ya hecho
  • Pide clarificación de un mensaje anterior

Si DUDAS, devuelve `mode: chat` y pregunta:
"¿Prefieres que armemos un flujo completo o te respondo directo?"

═══════════════════════════════════════════════════════════════════════════
COMPOSICIÓN DEL GRAFO — 7 REGLAS DURAS
═══════════════════════════════════════════════════════════════════════════

1. SIEMPRE exactamente 1 nodo `contexto` al inicio. Sin excepción.
2. SIEMPRE exactamente 1 nodo `entrega` al final. Sin excepción.
3. Mínimo 1 Agente, máximo 5 Agentes. Si el flujo natural exige más,
   divídelo con un nodo `revision` en el medio.
4. Paralelo (múltiples Agentes sin edge entre ellos apuntando al mismo
   destino) SOLO cuando las perspectivas son genuinamente independientes.
   El sistema los consolida invisiblemente vía SYNTHESIZER. NO uses
   paralelo solo por acelerar.
5. HITL (`revision`) SOLO cuando el flujo tiene >3 agentes o toca
   decisión estratégica. Evita HITL innecesario que frena al ejecutivo.
6. El `addendum` de cada Agente especifica su entregable CONCRETO.
   MAL: "analiza esto"
   BIEN: "propón 3 territorios creativos con tagline, 60 palabras por territorio"
7. El formato de `entrega` respeta lo que pidió el usuario. Si no lo pidió:
   brief → docx
   reporte / análisis → pdf
   presentación / kickoff → pptx
   lista de datos / tabla → xlsx
   respuesta corta / resumen → text

═══════════════════════════════════════════════════════════════════════════
NARRATIVA
═══════════════════════════════════════════════════════════════════════════

`narrative` = venta corta del plan. Máximo 3 frases.
  • Primera persona plural ("armamos un flujo…")
  • Menciona agentes por nombre (Valentina, no "la CMO")
  • Termina con CTA sutil ("dale al play cuando quieras" /
    "si prefieres ajustar algo, dime")

═══════════════════════════════════════════════════════════════════════════
FORMATO DE SALIDA (ESTRICTO)
═══════════════════════════════════════════════════════════════════════════

Devuelves SIEMPRE un único JSON, sin texto antes ni después.

Caso A — mode "graph":
{{
  "mode": "graph",
  "narrative": "string (máx 3 frases)",
  "graph": {{
    "nodes": [ {{ "id": "...", "type": "...", "data": {{...}} }}, ... ],
    "edges": [ {{ "source": "...", "target": "..." }}, ... ]
  }},
  "explanation_per_node": {{
    "<node_id>": "string (lo que aporta, 1 frase)"
  }}
}}

Caso B — mode "chat":
{{
  "mode": "chat",
  "message": "string"
}}

Schemas de `data` por tipo de nodo:

  contexto:
    {{ "text": string,
      "toggles": {{ "web": bool, "brandhub": string|null }},
      "attachments": [] }}

  agente:
    {{ "agent_id": string,
      "addendum": string,
      "model_override": string|null }}

  revision:
    {{ "prompt": string }}

  entrega:
    {{ "format": "text"|"docx"|"pptx"|"xlsx"|"pdf",
      "destination": "chat"|"email"|"onedrive" }}

════════════════════════════════════════════════════════════════════════════
REGLAS FINALES
════════════════════════════════════════════════════════════════════════════

• Nunca inventes agentes que no estén en el Legio roster.
• Nunca uses IDs de nodo duplicados.
• Nunca devuelvas texto fuera del JSON.
• Nunca escribas markdown, code fences, o prefijos en el output.
• Si no puedes cumplir la tarea (falta info crítica, petición ambigua),
  devuelve mode "chat" con un mensaje pidiendo la información mínima necesaria.
• Si el usuario pide algo que viola la constitución del tenant
  (ej. info de otra marca del tenant, ataque a competidor), devuelve mode
  "chat" explicando por qué no procede.
"""


# ═══════════════════════════════════════════════════════════════
# RENDER + INVOKE
# ═══════════════════════════════════════════════════════════════

def render_system_prompt(tenant_id: str) -> str:
    """Render the Architect system prompt with dynamic placeholders."""
    
    # Get tenant context
    conn = get_db_connection()
    tenant_constitution = ""
    brand_name = tenant_id.upper()
    try:
        tenant_constitution = get_tenant_context_with_fallback(conn, tenant_id)
        # Try to extract brand name from constitution
        if conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT brand_name FROM tenant_constitutions WHERE tenant_id = %s",
                        (tenant_id,)
                    )
                    row = cursor.fetchone()
                    if row and row.get("brand_name"):
                        brand_name = row["brand_name"]
            except Exception:
                pass
    finally:
        if conn:
            conn.close()
    
    return ARCHITECT_SYSTEM_PROMPT.format(
        tenant_id=tenant_id,
        brand_name=brand_name,
        current_date=datetime.utcnow().strftime("%Y-%m-%d"),
        tenant_constitution=tenant_constitution,
        legio_roster=build_legio_roster(),
    )


def _format_user_message(user_message: str, current_graph: Optional[dict] = None) -> str:
    """Format the user message, injecting current_graph if editing."""
    if current_graph:
        graph_json = json.dumps(current_graph, indent=2, ensure_ascii=False)
        return f"""El usuario tiene un grafo existente que quiere editar:

```json
{graph_json}
```

Solicitud del usuario: {user_message}"""
    return user_message


async def generate_graph(
    user_message: str,
    tenant_id: str,
    current_graph: Optional[dict] = None,
    chat_history: Optional[List[dict]] = None,
    model: str = "claude-sonnet-4-6",
) -> dict:
    """Invoke Shifty-Architect to generate a DAG from natural language.
    
    Args:
        user_message: The user's natural language intent
        tenant_id: Tenant ID for context injection
        current_graph: Existing graph if editing (optional)
        chat_history: Last N messages for conversational context
        model: LLM model to use
    
    Returns:
        dict: { mode, narrative?, graph?, explanation_per_node?, message? }
    """
    system_prompt = render_system_prompt(tenant_id)
    
    # Build messages array (history as prior messages, NOT in system prompt)
    messages = [SystemMessage(content=system_prompt)]
    
    if chat_history:
        for msg in chat_history[-6:]:  # Last 6 messages
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))
    
    # Current user message (with optional current_graph)
    formatted_message = _format_user_message(user_message, current_graph)
    messages.append(HumanMessage(content=formatted_message))
    
    # Invoke LLM
    architect_llm = get_llm(model)
    
    MAX_RETRIES = 2
    last_error = None
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            if attempt > 0:
                # Retry with error feedback
                messages.append(AIMessage(content=f"(Output inválido: {last_error})"))
                messages.append(HumanMessage(content="Corrige el JSON y vuelve a intentar. Solo JSON válido, sin texto."))
            
            response = await architect_llm.ainvoke(messages)
            raw_output = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON
            result = _parse_architect_output(raw_output)
            
            # Validate
            validation_error = _validate_graph_output(result)
            if validation_error:
                last_error = validation_error
                print(f"[ARCHITECT] Validation failed (attempt {attempt + 1}): {validation_error}")
                if attempt < MAX_RETRIES:
                    continue
                else:
                    # Return as-is after max retries, let frontend handle gracefully
                    print(f"[ARCHITECT] Max retries reached. Returning partial result.")
                    return result
            
            print(f"[ARCHITECT] ✓ Generated mode={result['mode']} (attempt {attempt + 1})")
            return result
            
        except Exception as e:
            last_error = str(e)
            print(f"[ARCHITECT] Error (attempt {attempt + 1}): {e}")
            if attempt >= MAX_RETRIES:
                # Ultimate fallback — return chat mode with error message
                return {
                    "mode": "chat",
                    "message": "No pude armar el flujo. ¿Puedes darme más detalles sobre lo que necesitas?"
                }
    
    return {"mode": "chat", "message": "Error interno del arquitecto."}


# ═══════════════════════════════════════════════════════════════
# PARSING & VALIDATION
# ═══════════════════════════════════════════════════════════════

def _parse_architect_output(raw: str) -> dict:
    """Parse the architect's JSON output, handling markdown fences."""
    text = raw.strip()
    
    # Strip markdown code fences
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    
    return json.loads(text)


def _validate_graph_output(result: dict) -> Optional[str]:
    """Validate the architect's output. Returns error string or None if valid."""
    
    # 1. mode check
    mode = result.get("mode")
    if mode not in ("graph", "chat"):
        return f"Invalid mode: {mode}. Must be 'graph' or 'chat'"
    
    # If chat mode, just needs a message
    if mode == "chat":
        if not result.get("message"):
            return "mode=chat but no 'message' field"
        return None
    
    # 2. graph mode validations
    graph = result.get("graph", {})
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    
    if not nodes:
        return "graph.nodes is empty"
    
    # 3. Exactly 1 contexto at start, 1 entrega at end
    contexto_nodes = [n for n in nodes if n.get("type") == "contexto"]
    entrega_nodes = [n for n in nodes if n.get("type") == "entrega"]
    
    if len(contexto_nodes) != 1:
        return f"Expected exactly 1 'contexto' node, got {len(contexto_nodes)}"
    if len(entrega_nodes) != 1:
        return f"Expected exactly 1 'entrega' node, got {len(entrega_nodes)}"
    
    # 4. All agent_ids exist in AGENTS registry
    agent_nodes = [n for n in nodes if n.get("type") == "agente"]
    for node in agent_nodes:
        agent_id = node.get("data", {}).get("agent_id", "")
        if agent_id not in AGENTS:
            return f"agent_id '{agent_id}' not found in Legio roster. Available: {list(AGENTS.keys())}"
    
    # 5. Unique node IDs
    node_ids = [n.get("id") for n in nodes]
    if len(node_ids) != len(set(node_ids)):
        duplicates = [nid for nid in node_ids if node_ids.count(nid) > 1]
        return f"Duplicate node IDs: {set(duplicates)}"
    
    # 6. Edges reference existing nodes
    node_id_set = set(node_ids)
    for edge in edges:
        if edge.get("source") not in node_id_set:
            return f"Edge source '{edge.get('source')}' not in nodes"
        if edge.get("target") not in node_id_set:
            return f"Edge target '{edge.get('target')}' not in nodes"
    
    # 7. DAG check (no cycles)
    cycle_error = _detect_cycles(node_ids, edges)
    if cycle_error:
        return cycle_error
    
    # 8. narrative exists
    if not result.get("narrative"):
        return "Missing 'narrative' field"
    
    return None  # Valid!


def _detect_cycles(node_ids: List[str], edges: List[dict]) -> Optional[str]:
    """Detect cycles in the graph using DFS. Returns error or None."""
    adj: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src in adj:
            adj[src].append(tgt)
    
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in node_ids}
    
    def dfs(node: str) -> bool:
        color[node] = GRAY
        for neighbor in adj.get(node, []):
            if color.get(neighbor) == GRAY:
                return True  # Cycle!
            if color.get(neighbor) == WHITE:
                if dfs(neighbor):
                    return True
        color[node] = BLACK
        return False
    
    for nid in node_ids:
        if color[nid] == WHITE:
            if dfs(nid):
                return "Cycle detected in graph — DAG must be acyclic"
    
    return None
