"""
Peaje insight-router client.

Pega entre la extracción del insight (peaje/extractor.py) y el INSERT
final en peaje_insights (peaje/ingest.py). Su único trabajo:

  1. Cargar las sub-categorías VÁLIDAS para source_app desde
     peaje_app_taxonomy. La capa Python pre-filtra para que el agente
     no pueda inventar `subcategory_key` que no existan.

  2. Invocar el skill `insight-router` con el payload exacto que su
     YAML especifica.

  3. Validar el JSON devuelto contra el contrato (campos requeridos,
     dominios cerrados de enums, sub_category dentro del set válido,
     confidence en [0,1]). Cualquier desviación → marca review_required
     y degrada confidence a 0.0 para que un humano revise en
     /admin/punto-medio.

  4. Persistir la decisión completa en peaje_router_decisions (audit).

  5. Devolver un dict normalizado que el ingest puede consumir directo:
       {
         decided_app, canonical_category, sub_category,
         promote_to_global, scope, confidence, review_required, ...
       }

Diseñado para fallar abierto: si el LLM se cae, devolvemos un default
seguro (decided_app=source_app, scope=tenant, promote_to_global=False,
review_required=True) en vez de tirar la ingest. La cola de revisión
absorbe los casos degradados.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from agents.registry import AGENTS
from config.database import get_db_connection
from config.models import get_llm

# ─── Config ─────────────────────────────────────────────────────────

ROUTER_AGENT_ID = "insight-router"
ROUTER_VERSION = "1.0.0"

# Modelo por defecto para clasificación. Cheap + JSON-stable.
ROUTER_MODEL = os.getenv(
    "PEAJE_ROUTER_MODEL",
    "google/gemini-3.1-flash-lite-preview",
)

# Umbrales de confianza para review automático
AUTO_APPROVE_THRESHOLD = 0.85   # ≥ esto: review_required permanece como diga el LLM
REVIEW_FORCE_THRESHOLD = 0.60   # < esto: forzamos review_required = True

# Dominios cerrados (espejo del schema v3)
VALID_APPS = {"cl2", "eco", "studio", "sentinel"}
VALID_CANONICAL = {
    "riesgos_ciegos",
    "patrones_sectoriales",
    "gaps_productividad",
    "vectores_aceleracion",
}
VALID_SCOPES = {"tenant", "global"}


# ─── Helpers ────────────────────────────────────────────────────────


def _load_subcategories_for_app(app_id: str) -> List[Dict[str, str]]:
    """Lee peaje_app_taxonomy y devuelve la lista que va al input
    `available_subcategories` del agente. Falla suave: si la tabla
    no existe (migración v3 no aplicada todavía) devuelve []."""
    conn = get_db_connection()
    if conn is None:
        return []
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT subcategory_key, canonical_category, subcategory_label
                  FROM peaje_app_taxonomy
                 WHERE app_id = %s AND is_active = TRUE
                 ORDER BY canonical_category, sort_order
                """,
                (app_id,),
            )
            rows = cursor.fetchall() or []
        return [
            {
                "key": r["subcategory_key"],
                "canonical": r["canonical_category"],
                "label": r["subcategory_label"],
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[ROUTER] Subcategory load failed for app={app_id}: {e}")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _safe_default(source_app: str, reason: str) -> Dict[str, Any]:
    """Decisión por defecto cuando el agente falla o devuelve basura.
    Mantiene el flujo vivo (no rompemos ingest) y manda a revisión
    humana. Mejor un bucket conservador que un crash."""
    return {
        "decided_app": source_app if source_app in VALID_APPS else "cl2",
        "canonical_category": "riesgos_ciegos",   # default conservador
        "sub_category": None,
        "promote_to_global": False,
        "promote_rationale": None,
        "scope": "tenant",
        "confidence": 0.0,
        "review_required": True,
        "review_reason": f"router_fallback: {reason}",
        "tags": ["router_failed"],
        "router_notes": reason[:200],
    }


def _validate_decision(
    raw: Any,
    source_app: str,
    valid_subcat_keys: set,
) -> Dict[str, Any]:
    """Verifica el JSON contra el contrato del YAML. Cualquier fallo
    cae al fallback. Sin esto un agente alucinado puede meter
    `decided_app='banana'` y romper el FK del INSERT downstream."""
    if not isinstance(raw, dict):
        return _safe_default(source_app, "non_dict_output")

    decided_app = raw.get("decided_app")
    if decided_app not in VALID_APPS:
        return _safe_default(source_app, f"bad_decided_app:{decided_app}")

    canonical = raw.get("canonical_category")
    if canonical not in VALID_CANONICAL:
        return _safe_default(source_app, f"bad_canonical:{canonical}")

    sub = raw.get("sub_category")
    if sub is not None and sub not in valid_subcat_keys:
        # No abortamos — degradamos sub_category a None pero conservamos
        # el resto de la decisión. Forzamos review.
        sub = None
        raw["review_required"] = True
        raw["review_reason"] = (raw.get("review_reason") or "") + " | invalid_subcategory_dropped"

    scope = raw.get("scope")
    if scope not in VALID_SCOPES:
        scope = "tenant"

    promote = bool(raw.get("promote_to_global", False))
    rationale = raw.get("promote_rationale")
    if promote and not rationale:
        # Contrato dice rationale obligatorio si promote=True. Si no
        # vino, degradamos a no-promote y mandamos a review.
        promote = False
        raw["review_required"] = True
        raw["review_reason"] = (raw.get("review_reason") or "") + " | promote_without_rationale"

    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    review_required = bool(raw.get("review_required", False))
    if confidence < REVIEW_FORCE_THRESHOLD:
        review_required = True

    tags = raw.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    tags = [str(t)[:60] for t in tags[:5]]

    return {
        "decided_app": decided_app,
        "canonical_category": canonical,
        "sub_category": sub,
        "promote_to_global": promote,
        "promote_rationale": (rationale or None) if promote else None,
        "scope": scope,
        "confidence": round(confidence, 3),
        "review_required": review_required,
        "review_reason": raw.get("review_reason"),
        "tags": tags,
        "router_notes": (raw.get("router_notes") or "")[:200],
    }


def _persist_decision(
    insight_id: int,
    source_app: str,
    decision: Dict[str, Any],
    raw_output: Any,
) -> None:
    """Guarda la decisión en peaje_router_decisions. Best-effort: si
    la tabla no existe (migración v3 sin aplicar) o el INSERT falla,
    loggeamos y seguimos."""
    conn = get_db_connection()
    if conn is None:
        return
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO peaje_router_decisions (
                    insight_id, source_app, decided_app,
                    canonical_category, sub_category,
                    promote_to_global, promote_rationale,
                    confidence, review_required,
                    router_model, router_version, raw_output
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    insight_id,
                    source_app,
                    decision["decided_app"],
                    decision["canonical_category"],
                    decision["sub_category"],
                    decision["promote_to_global"],
                    decision["promote_rationale"],
                    decision["confidence"],
                    decision["review_required"],
                    ROUTER_MODEL,
                    ROUTER_VERSION,
                    json.dumps(raw_output, ensure_ascii=False) if raw_output else None,
                ),
            )
            conn.commit()
    except Exception as e:
        print(f"[ROUTER] Persist decision failed: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ─── Public API ─────────────────────────────────────────────────────


async def route_insight(
    *,
    insight_id: Optional[int],
    source_app: str,
    tenant_id: str,
    industry_vertical: Optional[str],
    insight_text: str,
    extraction_model: str,
    session_type: str = "chat",
    tenant_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Invoca el skill insight-router y devuelve la decisión validada.

    Args:
        insight_id: ID en peaje_insights si ya existe; None para
            decisiones pre-INSERT (válido — el audit row se inserta
            después del INSERT principal con el id real).
        source_app: 'cl2' | 'eco' | 'studio' | 'sentinel'.
        tenant_id: tenant que originó el insight.
        industry_vertical: vertical del tenant (puede ser None).
        insight_text: texto ya scrubbed de PII.
        extraction_model: modelo LLM que extrajo el insight (audit).
        session_type: 'chat' | 'debate' | 'embed' | 'run'.
        tenant_metadata: opcional, lo que el caller quiera anexar.

    Returns:
        dict con la forma del SALIDA del agente, ya validada y
        normalizada. Nunca lanza — fallback seguro al default.
    """
    if source_app not in VALID_APPS:
        return _safe_default("cl2", f"invalid_source_app:{source_app}")

    info = AGENTS.get(ROUTER_AGENT_ID)
    if info is None:
        # YAML no cargó (problema de deploy). No bloqueamos ingest.
        return _safe_default(source_app, "router_skill_not_registered")

    available = _load_subcategories_for_app(source_app)
    valid_keys = {s["key"] for s in available}

    payload = {
        "insight_id": insight_id,
        "source_app": source_app,
        "tenant_id": tenant_id,
        "industry_vertical": industry_vertical,
        "insight_text": insight_text,
        "context": {
            "extraction_model": extraction_model,
            "session_type": session_type,
            "tenant_metadata": tenant_metadata,
        },
        "available_subcategories": available,
    }

    system_prompt = info.get("skill", "") or ""
    user_message = json.dumps(payload, ensure_ascii=False, indent=2)

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        llm = get_llm(ROUTER_MODEL)
        # Determinismo: routing es clasificación, no creatividad.
        try:
            llm.temperature = 0.0
            llm.max_tokens = 800
        except Exception:
            pass

        t0 = time.time()
        result = await llm.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
        )
        latency_ms = int((time.time() - t0) * 1000)
        text = getattr(result, "content", "") or ""
    except Exception as e:
        print(f"[ROUTER] LLM call failed: {e}")
        decision = _safe_default(source_app, f"llm_call_failed:{type(e).__name__}")
        if insight_id is not None:
            _persist_decision(insight_id, source_app, decision, None)
        return decision

    # Best-effort JSON parse (idéntico a agents/router.py para
    # consistencia con cómo el HTTP endpoint trataría la salida).
    cleaned = text.strip()
    if cleaned.startswith("```"):
        nl = cleaned.find("\n")
        if nl >= 0:
            cleaned = cleaned[nl + 1 :]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    try:
        raw = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        decision = _safe_default(source_app, "json_parse_failed")
        if insight_id is not None:
            _persist_decision(insight_id, source_app, decision, {"raw_text": text[:1000]})
        return decision

    decision = _validate_decision(raw, source_app, valid_keys)
    decision["_latency_ms"] = latency_ms

    if insight_id is not None:
        _persist_decision(insight_id, source_app, decision, raw)

    print(
        f"[ROUTER] app={source_app}→{decision['decided_app']} "
        f"cat={decision['canonical_category']} sub={decision['sub_category']} "
        f"global={decision['promote_to_global']} conf={decision['confidence']} "
        f"review={decision['review_required']} ({latency_ms}ms)"
    )
    return decision
