"""Graph Nodes — Agent node factory functions for the swarm."""
from typing import Dict, Any
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool

from config.database import get_db_connection
from config.models import get_llm
from agents.registry import AGENTS
from agents.context import SHIFT_LAB_CONTEXT, PUNTO_MEDIO_GLOBAL_RAG, TENANT_CONTEXTS
from graph.state import SwarmState
from punto_medio import get_dynamic_rag, SEED_TENANT_CONTEXTS
from tenant_constitution import get_tenant_context_with_fallback

# ═══════════════════════════════════════════════════════════════
# TOOLS
# ═══════════════════════════════════════════════════════════════

# Import all tools (document generation, analysis, visualization)
from tools import ALL_TOOLS

@tool
def write_file_tool(path: str, content: str):
    """Escribe contenido directamente en un archivo del repositorio."""
    return f"SOLICITUD_ESCRITURA: {path}"

@tool
def read_file_tool(path: str):
    """Lee el contenido de un archivo del repositorio."""
    return f"SOLICITUD_LECTURA: {path}"

@tool
def execute_command_tool(command: str):
    """Ejecuta un comando en el sistema."""
    return f"SOLICITUD_COMANDO: {command}"

@tool
def search_code_tool(query: str, file_pattern: str = "*"):
    """Busca código en el repositorio usando regex."""
    return f"SOLICITUD_BUSQUEDA: {query} en archivos {file_pattern}"

# Combine all tools: system tools + document tools + extended tools
tools = [write_file_tool, read_file_tool, execute_command_tool, search_code_tool] + ALL_TOOLS

# Catálogo por nombre — para resolución en tool_map.get_tools_for_agent
TOOL_CATALOG = {t.name: t for t in tools}


def create_agent_node_with_model(agent_id: str, model_name: str, tenant_id: str = "shift", user_metadata: dict = None):
    """Factory function para crear nodos de agentes con modelo específico e inyección de RAG/Tenant DINÁMICO + Identity User."""
    def agent_node(state: SwarmState):
        agent_info = AGENTS[agent_id]
        # Asegurar que tid sea siempre string
        tid = str(tenant_id) if tenant_id is not None else "shift"
        
        # ═══════════════════════════════════════════════════════════
        # DYNAMIC RAG INJECTION — Punto Medio v2.0
        # ═══════════════════════════════════════════════════════════
        try:
            rag_conn = get_db_connection()
            dynamic_rag = get_dynamic_rag(rag_conn, tid)
            punto_medio_injection = dynamic_rag["combined_rag"]
            if rag_conn:
                rag_conn.close()
        except Exception as rag_err:
            print(f"[DYNAMIC RAG] Falling back to seed: {rag_err}")
            punto_medio_injection = PUNTO_MEDIO_GLOBAL_RAG
        
        # Tenant context: try dynamic first, then hardcoded seed
        conn = get_db_connection()
        tenant_context = get_tenant_context_with_fallback(conn, tid)
        
        # Security: Read Only Mode check
        read_only = True # Default to secure
        if conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT read_only_mode FROM tenant_constitutions WHERE tenant_id = %s", (tid,))
                    row = cursor.fetchone()
                    if row:
                        read_only = bool(row.get('read_only_mode', True))
            except Exception:
                pass
            finally:
                conn.close()

        # Define tools based on security mode
        from graph.tool_map import get_tools_for_agent
        active_tools = get_tools_for_agent(
            agent_id=agent_id,
            agent_info=agent_info,
            read_only=read_only,
            tool_catalog=TOOL_CATALOG,
        )
        if read_only:
            print(f"[SECURITY] Read-only mode active for {tid}. Write/Execute tools blocked.")

        # Detectar si estamos en Modo Nodos por parte del UI
        is_nodes_mode = any("[SYSTEM INSTRUCTION: MODO NODOS]" in m.content for m in state.get("messages", []))
        
        nodes_specialist_guardrail = """
# MODO NODOS ACTIVO (ENFORCEMENT ESTRICTO DE TEXTO)
Estás participando como un especialista en un flujo de trabajo de nodos visuales. 
Tu única misión es leer el contexto previo, aplicar tu conocimiento especializado y DEVOLVER TEXTO PLANO ORGÁNICO.
ESTRICTAMENTE PROHIBIDO:
- NO devuelvas estructuras JSON.
- NO imites al Orquestador devolviendo esquemas (nodes/edges).
- Limita tu respuesta a tu análisis narrativo experto, puedes usar subtítulos (Markdown).
""" if is_nodes_mode else ""

        # Get context from state (includes web search results if enabled)
        context_from_state = state.get("context", "")

        user_profile_context = ""
        if user_metadata:
            user_profile_context = f"""
# PERFIL DEL USUARIO (A QUIÉN LE HABLAS)
Nombre: {user_metadata.get('shift_name', 'Usuario')}
Área de Impacto: {user_metadata.get('shift_area', 'No especificada')}
Estilo de Interacción Solicitado: {user_metadata.get('shift_vibe', 'Estándar')}
INSTRUCCIÓN OBLIGATORIA: Dirígete al usuario por su nombre. Adapta tu tono, complejidad técnica y formato de respuesta para encajar perfectamente con su 'Estilo de Interacción Solicitado'.
"""

        # INYECCIÓN DEL RAG (Dynamic Graph Injection)
        system_content = f"""
{SHIFT_LAB_CONTEXT}

# CONTEXTO CORPORATIVO ({tid.upper()})
{tenant_context}

# CONTEXTO ORGANIZACIONAL RELEVANTE
{punto_medio_injection}

{user_profile_context}

{context_from_state}

# TU ROL ESPECIALIZADO
Nombre: {agent_info['name']}
{agent_info['skill']}

# INSTRUCCIONES OPERATIVAS (SOP)
1. **Detección de Idioma:** Responde SIEMPRE en el mismo idioma del usuario (ES/EN/PT). Tono profesional pero cercano.
2. **Formato Markdown:** Usa `##` para secciones, `**negritas**` para conceptos clave, bloques de código para comandos/datos estructurados.
3. **Longitud Adaptativa:** Preguntas simples → respuesta directa y breve. Solicitudes estratégicas/técnicas → respuesta estructurada y exhaustiva.
4. **Herramientas:** {"Tienes acceso a read_file_tool, search_code_tool." if read_only else "Tienes acceso a write_file_tool, read_file_tool, execute_command_tool, search_code_tool."} Úsalas inmediatamente si la intención del usuario es clara; no pidas permiso innecesario.
5. **Identidad inquebrantable:** Está PROHIBIDO decir "como modelo de lenguaje", "como IA", "consultando a mis compañeros", o cualquier referencia a sistemas internos, pipelines, arquitectura o componentes técnicos. Eres {agent_info['name']} de {tid.upper()}, punto.
6. **Protocolo de Incertidumbre:** Si no tienes visibilidad sobre un dato específico de {tid.upper()}, di: "No tengo visibilidad sobre [X] en este momento. ¿Quieres que proceda con una estimación basada en mejores prácticas del sector?"
7. **Accionabilidad Obligatoria:** Toda respuesta no-trivial debe cerrar con un Next Step concreto o pregunta de seguimiento.
8. **Continuidad Conversacional:** El historial puede contener respuestas previas de otros consultores del equipo, marcadas como `[Nombre]: texto`. Aprovecha ese contexto para dar continuidad — no repitas lo que ya se dijo, complementa o profundiza.

{nodes_specialist_guardrail}
"""
        
        # Use the selected model
        agent_llm = get_llm(model_name)
        bound_llm = agent_llm.bind_tools(active_tools)
        messages = [SystemMessage(content=system_content)] + state["messages"]
        response = bound_llm.invoke(messages)
        
        return {
            "messages": state["messages"] + [response],  # ✅ ACUMULAR historial completo
            "active_agent": agent_id,
            "agent_outputs": {**state.get("agent_outputs", {}), agent_id: response.content}
        }
    return agent_node


def create_async_agent_node(agent_id: str, model_name: str, tenant_id: str = "shift"):
    """Async factory for debate agents — avoids blocking the event loop during LLM calls."""
    async def agent_node_async(state: SwarmState):
        agent_info = AGENTS[agent_id]
        tid = str(tenant_id) if tenant_id is not None else "shift"
        
        # Dynamic RAG injection
        try:
            rag_conn = get_db_connection()
            dynamic_rag = get_dynamic_rag(rag_conn, tid)
            punto_medio_injection = dynamic_rag["combined_rag"]
            if rag_conn:
                rag_conn.close()
        except Exception as rag_err:
            print(f"[DYNAMIC RAG] Falling back to seed: {rag_err}")
            punto_medio_injection = PUNTO_MEDIO_GLOBAL_RAG
        
        conn = get_db_connection()
        tenant_context = TENANT_CONTEXTS.get(tid, SEED_TENANT_CONTEXTS.get(tid, TENANT_CONTEXTS.get("shift", "")))
        
        # Security: Read Only Mode check
        read_only = True # Default to secure
        if conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT read_only_mode FROM tenant_constitutions WHERE tenant_id = %s", (tid,))
                    row = cursor.fetchone()
                    if row:
                        read_only = bool(row.get('read_only_mode', True))
            except Exception:
                pass
            finally:
                conn.close()

        # Define tools based on security mode
        from graph.tool_map import get_tools_for_agent
        active_tools = get_tools_for_agent(
            agent_id=agent_id,
            agent_info=agent_info,
            read_only=read_only,
            tool_catalog=TOOL_CATALOG,
        )

        system_content = f"""
{SHIFT_LAB_CONTEXT}

# CONTEXTO CORPORATIVO ({tid.upper()})
{tenant_context}

# CONTEXTO ORGANIZACIONAL RELEVANTE
{punto_medio_injection}

# TU ROL ESPECIALIZADO
Nombre: {agent_info['name']}
{agent_info['skill']}

# INSTRUCCIONES OPERATIVAS (SOP)
1. **Detección de Idioma:** Responde SIEMPRE en el mismo idioma del usuario (ES/EN/PT). Tono profesional pero cercano.
2. **Formato Markdown:** Usa `##` para secciones, `**negritas**` para conceptos clave, bloques de código para comandos/datos estructurados.
3. **Longitud Adaptativa:** Preguntas simples → respuesta directa y breve. Solicitudes estratégicas/técnicas → respuesta estructurada y exhaustiva.
4. **Herramientas:** {"Tienes acceso a read_file_tool, search_code_tool." if read_only else "Tienes acceso a write_file_tool, read_file_tool, execute_command_tool, search_code_tool."} Úsalas inmediatamente si la intención del usuario es clara.
5. **Identidad inquebrantable:** Está PROHIBIDO decir "como modelo de lenguaje", "como IA", "consultando a mis compañeros", o cualquier referencia a sistemas internos, pipelines, arquitectura o componentes técnicos. Eres {agent_info['name']} de {tid.upper()}, punto.
6. **Protocolo de Incertidumbre:** Si no tienes visibilidad sobre un dato específico de {tid.upper()}, di: "No tengo visibilidad sobre [X] en este momento. ¿Quieres que proceda con una estimación basada en mejores prácticas del sector?"
7. **Accionabilidad Obligatoria:** Toda respuesta no-trivial debe cerrar con un Next Step concreto o pregunta de seguimiento.
"""
        
        agent_llm = get_llm(model_name)
        bound_llm = agent_llm.bind_tools(active_tools)

        # Multi-agent handoff fix: rebuild messages as [user_query + prior_agents_context]
        # so every agent sees a conversation that ends with a HumanMessage (required by
        # Azure-hosted Claude / providers that reject assistant prefill) and drops any
        # orphan tool_use blocks from prior agents' AIMessages.
        from langchain_core.messages import HumanMessage as _HM
        original_user = next((m for m in state["messages"] if m.__class__.__name__ == "HumanMessage"), None)
        prior_outputs = state.get("agent_outputs", {})
        if prior_outputs:
            prior_ctx = "\n\n---\n\n".join(
                f"**Perspectiva previa de {aid.upper()}:**\n{str(out)[:1800]}"
                for aid, out in prior_outputs.items()
            )
            composed = _HM(
                content=(
                    (original_user.content if original_user else "")
                    + f"\n\n---CONTEXTO MULTI-AGENTE---\n{prior_ctx}\n---FIN CONTEXTO---\n\n"
                    "Aporta tu perspectiva específica. No repitas lo ya dicho."
                )
            )
            call_messages = [SystemMessage(content=system_content), composed]
        else:
            call_messages = [SystemMessage(content=system_content)] + (
                [original_user] if original_user else state["messages"]
            )

        # ✅ ASYNC invoke — does NOT block the event loop
        response = await bound_llm.ainvoke(call_messages)

        return {
            "messages": state["messages"] + [response],
            "active_agent": agent_id,
            "agent_outputs": {**state.get("agent_outputs", {}), agent_id: response.content}
        }
    return agent_node_async
