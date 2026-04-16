"""Graph Synthesizer — Merges outputs from multiple agents into a unified response.
Used when execution_plan has >1 agent (multi-agent sequential flow)."""
from langchain_core.messages import SystemMessage, AIMessage
from config.models import get_llm
from agents.registry import AGENTS
from graph.state import SwarmState


SYNTHESIZER_PROMPT = """Eres el Sintetizador Estratégico de Shifty Studio. Acabas de recibir análisis de múltiples consultores especializados sobre la misma consulta del usuario.

# OUTPUTS DE LOS ESPECIALISTAS
{agent_outputs_text}

# TU MISIÓN
1. **Integra** las perspectivas de todos los especialistas en una respuesta cohesiva y accionable.
2. **Resuelve contradicciones** — si dos especialistas difieren, toma postura firme con justificación.
3. **Elimina redundancia** — no repitas lo que ya dijo cada uno, sintetiza.
4. **Estructura** la respuesta con secciones claras (Markdown).
5. **Cierra** con Next Steps concretos que combinen las recomendaciones de todos.

# REGLAS
- Nunca menciones el sistema multi-agente ni que "varios consultores" participaron.
- Presenta la respuesta como si fuera de un solo consultor senior que domina todos los ángulos.
- El usuario debe sentir que recibió UNA respuesta integral, no un collage de opiniones.
- Idioma: responde en el mismo idioma del usuario.
"""


async def synthesizer_node(state: SwarmState) -> dict:
    """LangGraph node: Synthesizes multiple agent outputs into one unified response.
    Only runs when execution_plan has >1 agent."""
    
    agent_outputs = state.get("agent_outputs", {})
    
    # If only 1 agent ran, no synthesis needed
    if len(agent_outputs) <= 1:
        print("[SYNTHESIZER] Single agent — no synthesis needed")
        return {}
    
    # Build the outputs text for the prompt
    outputs_parts = []
    for agent_id, output in agent_outputs.items():
        agent_name = AGENTS.get(agent_id, {}).get("name", agent_id)
        agent_role = AGENTS.get(agent_id, {}).get("role", "Specialist")
        outputs_parts.append(f"## {agent_name} ({agent_role})\n{output}")
    
    agent_outputs_text = "\n\n---\n\n".join(outputs_parts)
    
    # Use the same model as the agents for consistency
    model_name = state.get("model_name", "Claude 3.5 Sonnet")
    synth_llm = get_llm(model_name)
    
    prompt = SYNTHESIZER_PROMPT.format(agent_outputs_text=agent_outputs_text)
    
    print(f"[SYNTHESIZER] Merging {len(agent_outputs)} agent outputs: {list(agent_outputs.keys())}")
    
    response = await synth_llm.ainvoke([SystemMessage(content=prompt)])
    synthesis = response.content if hasattr(response, 'content') else str(response)
    
    print(f"[SYNTHESIZER] ✓ Synthesis complete: {len(synthesis)} chars")
    
    return {
        "messages": state["messages"] + [AIMessage(content=synthesis)],
        "active_agent": "synthesizer",
    }
