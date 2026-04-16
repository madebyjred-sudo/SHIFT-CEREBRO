"""Peaje Extractor — Agentic insight extraction using LLM."""
import json
from typing import List
from langchain_core.messages import SystemMessage
from config.models import get_llm
from graph.state import ChatMessage


async def extract_insight_data_async(messages: List[ChatMessage], response: str, tenant_id: str) -> dict:
    """Extractor Agéntico para 'El Peaje': Destila Insights, Gaps y Patrones con Anonimización NER."""
    
    # Preparamos la conversación para el LLM
    conversation_text = "\n".join([f"{m.role.upper()}: {m.content}" for m in messages])
    conversation_text += f"\nASSISTANT: {response}"
    
    extractor_prompt = f"""
Eres el 'Pattern Extractor & NER Anonymizer' de Shifty Studio (Punto Medio).
Tu misión es procesar la siguiente conversación de un ejecutivo y extraer la inteligencia estructural.

REGLAS DE ANONIMIZACIÓN (NER):
- Elimina NOMBRES de personas, empresas, proyectos específicos o clientes.
- Elimina MÉTRICAS financieras exactas o KPIs crudos (ej: de '$5M' a 'capital intensivo').
- Sustituye localizaciones por regiones macro (ej: de 'Santiago' a 'cono sur').

TAXONOMÍA REQUERIDA (Elige la más relevante):
- "Riesgos Ciegos Detectados"
- "Patrones de Decisión Sectorial"
- "Gaps de Productividad Institucional"
- "Vectores de Aceleración Ocultos"

FORMATO DE INSIGHT:
El `insight_text` DEBE seguir este formato denso exactamente:
'Observation: [X] | Impact: [Y] | Actionable Vector: [Z]'

CONVERSACIÓN:
{conversation_text}

Debes responder ÚNICAMENTE con un JSON válido con esta estructura exacta:
{{
    "insight_text": "Observation: ... | Impact: ... | Actionable Vector: ...",
    "category": "Una de las 4 taxonomías requeridas",
    "sentiment": "positive, negative, o neutral",
    "confidence_score": 0.95
}}
    """
    
    try:
        # Usamos el modelo GRATUITO de MiniMax en OpenRouter para no consumir saldo del Peaje
        extraction_llm = get_llm("minimax/minimax-m2.5") 
        result = await extraction_llm.ainvoke([SystemMessage(content=extractor_prompt)])
        
        # Limpiar posible markdown block
        json_str = result.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(json_str)
        
        return {
            "insight_text": data.get("insight_text", "Extracción genérica de interacción"),
            "category": data.get("category", "Vectores de Aceleración Ocultos"),
            "sentiment": data.get("sentiment", "neutral"),
            "confidence_score": data.get("confidence_score", 0.50)
        }
    except Exception as e:
        print(f"[EXTRACTOR ERROR] {e} - Cayendo a heurística básica")
        return {
            "insight_text": "Interacción registrada sin extracción profunda",
            "category": "Patrones de Decisión Sectorial",
            "sentiment": "neutral",
            "confidence_score": 0.10
        }


# Legacy function - kept for compatibility
async def extract_insight(messages: List[ChatMessage], response: str) -> dict:
    """Extract actionable insight from conversation (El Peaje v0.1)"""
    return await extract_insight_data_async(messages, response, "shift")
