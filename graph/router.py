"""Graph Router — LLM-as-Router for intelligent agent selection.
v2.0: Replaces keyword matching with an LLM call (Gemini Flash Lite / DeepSeek V3.2)
that returns agent_id + confidence + reasoning + execution_plan (multi-agent sequences)."""
import json
from typing import Dict, List, Tuple
from langchain_core.messages import SystemMessage, HumanMessage

from config.models import get_llm
from agents.registry import AGENTS
from graph.state import SwarmState


# ═══════════════════════════════════════════════════════════════
# ROUTER PROMPT — Crafted for fast, cheap LLMs
# ═══════════════════════════════════════════════════════════════

def _build_roster_text() -> str:
    """Build the agent roster section for the router prompt."""
    lines = []
    for agent_id, info in AGENTS.items():
        lines.append(f"- **{agent_id}**: {info['name']} — {info['role']} (keywords: {', '.join(info['keywords'][:5])})")
    return "\n".join(lines)


ROUTER_SYSTEM_PROMPT = """Eres el Router Inteligente de Shifty Studio. Tu ÚNICA misión es analizar el mensaje del usuario y decidir qué agente(s) del roster deben responder.

# ROSTER DE AGENTES DISPONIBLES
{roster}

# REGLAS DE ROUTING
1. **Single Agent (default):** La mayoría de consultas requieren 1 solo agente. Elige el más relevante.
2. **Multi-Agent (secuencial):** Si la consulta cruza dominios (ej: "Hazme un plan de marketing con presupuesto y análisis legal"), asigna una secuencia ordenada de 2-4 agentes.
3. **Fallback:** Si no hay match claro con ningún especialista, asigna "shiftai" (orquestador general).
4. **Confianza:** Si estás >80% seguro del routing, pon confidence alto. Si dudas, bájalo y asigna "shiftai".

# FORMATO DE RESPUESTA (JSON ESTRICTO)
Responde ÚNICAMENTE con un JSON válido, sin texto antes ni después:
```json
{{
    "agent_id": "id_del_agente_principal",
    "execution_plan": ["agent_1", "agent_2"],
    "confidence": 0.95,
    "reasoning": "Explicación breve de por qué este(os) agente(s)"
}}
```

REGLAS DEL JSON:
- `agent_id`: el primer agente de la secuencia (string)
- `execution_plan`: lista ordenada de agent IDs. Si es 1 solo agente, la lista tiene 1 elemento.
- `confidence`: float entre 0.0 y 1.0
- `reasoning`: string corto (1-2 frases)
"""


async def route_with_llm(message_content: str) -> Dict:
    """Use a cheap/fast LLM to intelligently route the user message to the right agent(s).
    
    Returns:
        dict with: agent_id, execution_plan, confidence, reasoning
    """
    try:
        # Use cheap model for routing — Gemini Flash Lite or DeepSeek
        router_llm = get_llm("google/gemini-3.1-flash-lite-preview")
        
        roster_text = _build_roster_text()
        system = ROUTER_SYSTEM_PROMPT.format(roster=roster_text)
        
        response = await router_llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=message_content)
        ])
        
        # Parse JSON response
        json_str = response.content.strip()
        # Handle markdown code blocks
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()
        
        result = json.loads(json_str)
        
        # Validate agent IDs exist
        agent_id = result.get("agent_id", "shiftai")
        if agent_id not in AGENTS:
            agent_id = "shiftai"
        
        plan = result.get("execution_plan", [agent_id])
        validated_plan = [aid for aid in plan if aid in AGENTS]
        if not validated_plan:
            validated_plan = [agent_id]
        
        confidence = min(max(float(result.get("confidence", 0.5)), 0.0), 1.0)
        reasoning = result.get("reasoning", "Router automático")
        
        print(f"[LLM ROUTER] ✓ Plan: {validated_plan} | Confidence: {confidence:.2f} | {reasoning}")
        
        return {
            "agent_id": validated_plan[0],
            "execution_plan": validated_plan,
            "confidence": confidence,
            "reasoning": reasoning,
        }
        
    except Exception as e:
        print(f"[LLM ROUTER] Error: {e} — falling back to keyword matcher")
        # Graceful fallback to keyword matching
        fallback_agent = determine_agent_from_message(message_content)
        return {
            "agent_id": fallback_agent,
            "execution_plan": [fallback_agent],
            "confidence": 0.3,
            "reasoning": f"Fallback keyword match: {fallback_agent}",
        }


def determine_agent_from_message(message_content: str) -> str:
    """Legacy keyword matcher — used as fallback when LLM router fails."""
    message_lower = message_content.lower()
    
    agent_scores: Dict[str, int] = {}
    for agent_id, agent_info in AGENTS.items():
        score = sum(1 for keyword in agent_info["keywords"] if keyword in message_lower)
        if score > 0:
            agent_scores[agent_id] = score
    
    if agent_scores:
        best_agent = ""
        max_score = 0
        for agent, score in agent_scores.items():
            if score > max_score:
                max_score = score
                best_agent = agent
        return best_agent if best_agent else "shiftai"
    
    return "shiftai"


async def arouter_node(state: SwarmState) -> dict:
    """Async LangGraph node: Routes using LLM-as-router.
    Used when the graph is invoked with ainvoke()."""
    
    # If plan is pre-set, skip routing
    if state.get("execution_plan") and len(state["execution_plan"]) > 0:
        print(f"[ROUTER NODE] Pre-set plan: {state['execution_plan']}")
        return {}  # No state changes needed
    
    # Get the last user message
    last_message = ""
    for msg in reversed(state["messages"]):
        if hasattr(msg, 'content') and isinstance(msg.content, str):
            last_message = msg.content
            break
    
    result = await route_with_llm(last_message)
    
    return {
        "execution_plan": result["execution_plan"],
        "current_step": 0,
        "active_agent": result["agent_id"],
        "router_reasoning": result["reasoning"],
        "router_confidence": result["confidence"],
    }
