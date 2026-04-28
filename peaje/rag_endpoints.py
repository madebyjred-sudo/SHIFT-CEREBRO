"""
Per-app RAG retrieval HTTP surface.

Endpoint exposed:

    GET /v1/rag/retrieve?app=eco&tenant=acme&category=...&k=15

    Returns the merged view (App RAG + Global RAG) that ONE app
    should see. Eco never sees CL2 directly; if a CL2 insight was
    promoted to global, it's visible — otherwise no.

    Scoping rules:
      - app_id matches  → APP RAG row (visible to that app only)
      - is_global=TRUE  → GLOBAL RAG row (visible to all apps)
      - approval_status='approved' (always)
      - tenant filter:
          * scope='global' rows have tenant_id NULL → always pass
          * scope='tenant' rows must match the requested tenant
            (or be skipped if no tenant supplied)

Designed so each app calls one endpoint with its own `app` id and
gets exactly what it should see — the boundary is enforced
server-side. No client-side filtering.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from config.database import get_db_connection

router = APIRouter()


VALID_APPS = {"cl2", "eco", "studio", "sentinel"}
VALID_CANONICAL = {
    "riesgos_ciegos",
    "patrones_sectoriales",
    "gaps_productividad",
    "vectores_aceleracion",
}


def _resolve_k(app_id: str, requested_k: Optional[int]) -> int:
    """Pull per-app default k from peaje_apps.rag_strategy. Caller
    can override via ?k=, but we cap at 50 to keep prompts sane."""
    if requested_k is not None:
        return max(1, min(50, int(requested_k)))

    conn = get_db_connection()
    if conn is None:
        return 15  # safe default
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT rag_strategy FROM peaje_apps WHERE app_id = %s",
                (app_id,),
            )
            row = cursor.fetchone()
        if not row or not row.get("rag_strategy"):
            return 15
        strategy = row["rag_strategy"]
        # rag_strategy is JSON; pyMySQL returns it as str on some
        # drivers, dict on others. Normalize.
        if isinstance(strategy, str):
            import json
            strategy = json.loads(strategy)
        return max(1, min(50, int(strategy.get("k", 15))))
    except Exception:
        return 15
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/v1/rag/retrieve")
async def retrieve_rag(
    app: str = Query(..., description="app_id: cl2|eco|studio|sentinel"),
    tenant: Optional[str] = Query(None, description="tenant_id; required for scope=tenant rows"),
    category: Optional[str] = Query(None, description="filtra por canonical_category (opcional)"),
    industry: Optional[str] = Query(None, description="filtra por industry_vertical (opcional)"),
    include_global: bool = Query(True, description="si False, sólo App RAG (debug)"),
    k: Optional[int] = Query(None, description="override del k por defecto del app"),
) -> Dict[str, Any]:
    """Retrieve RAG entries for ONE app.

    Devuelve un dict:
      {
        ok: true,
        app: <app_id>,
        k: <int>,
        rows: [ { ... punto_medio_consolidated row + labels ... } ],
        breakdown: { app_local: <int>, global_promoted: <int> }
      }
    """
    if app not in VALID_APPS:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_app", "valid": sorted(VALID_APPS)},
        )
    if category is not None and category not in VALID_CANONICAL:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_category", "valid": sorted(VALID_CANONICAL)},
        )

    k_final = _resolve_k(app, k)

    # Build dynamic WHERE. Mantenemos seguro contra SQL injection
    # parametrizando todos los inputs; los strings que concatenamos
    # son literales del propio código.
    where = ["pm.approval_status = 'approved'"]
    params: List[Any] = []

    # app + global scoping
    if include_global:
        where.append("(pm.app_id = %s OR pm.is_global = TRUE)")
        params.append(app)
    else:
        where.append("pm.app_id = %s AND pm.is_global = FALSE")
        params.append(app)

    # tenant scoping: scope='global' rows pass through; scope='tenant'
    # rows must match the requested tenant (else hidden).
    if tenant:
        where.append("(pm.scope = 'global' OR pm.tenant_id = %s)")
        params.append(tenant)
    else:
        where.append("pm.scope = 'global'")

    if category:
        where.append("pm.category = %s")
        params.append(category)

    if industry:
        where.append("pm.industry_vertical = %s")
        params.append(industry)

    where_sql = " AND ".join(where)

    sql = f"""
        SELECT
            pm.id,
            pm.app_id,
            pm.is_global,
            pm.promoted_from_app,
            pm.scope,
            pm.tenant_id,
            pm.category,
            pm.sub_category,
            pm.industry_vertical,
            pm.consolidated_text,
            pm.confidence_score,
            pm.contributing_tenants,
            pm.approved_at,
            pm.created_at,
            tax.category_label,
            sub.subcategory_label
          FROM punto_medio_consolidated pm
          LEFT JOIN peaje_taxonomy tax  ON tax.category_key = pm.category
          LEFT JOIN peaje_app_taxonomy sub
                 ON sub.subcategory_key = pm.sub_category
                AND sub.app_id = pm.app_id
         WHERE {where_sql}
         ORDER BY pm.is_global ASC,            -- App RAG primero (más específico)
                  pm.confidence_score DESC,
                  pm.approved_at DESC
         LIMIT %s
    """
    params.append(k_final)

    conn = get_db_connection()
    if conn is None:
        raise HTTPException(status_code=503, detail={"error": "db_unavailable"})
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall() or []
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "rag_query_failed", "message": str(e)[:500]},
        ) from e
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Normaliza tipos para JSON serialization (datetime, Decimal)
    def _ser(row: Dict[str, Any]) -> Dict[str, Any]:
        out = {}
        for k_, v in row.items():
            if hasattr(v, "isoformat"):
                out[k_] = v.isoformat()
            elif hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                out[k_] = float(v)
            else:
                out[k_] = v
        return out

    serialized = [_ser(r) for r in rows]

    breakdown = {
        "app_local": sum(1 for r in serialized if not r.get("is_global")),
        "global_promoted": sum(1 for r in serialized if r.get("is_global")),
    }

    return {
        "ok": True,
        "app": app,
        "tenant": tenant,
        "k": k_final,
        "count": len(serialized),
        "breakdown": breakdown,
        "rows": serialized,
    }


@router.get("/v1/rag/apps")
async def list_apps() -> Dict[str, Any]:
    """Registry handle — lo usa /admin/punto-medio para el filtro
    de app y el insight-router para conocer la lista de apps activas.
    """
    conn = get_db_connection()
    if conn is None:
        raise HTTPException(status_code=503, detail={"error": "db_unavailable"})
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT app_id, display_name, domain, active, rag_strategy "
                "FROM peaje_apps ORDER BY app_id"
            )
            rows = cursor.fetchall() or []
        return {"ok": True, "apps": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "apps_query_failed", "message": str(e)[:500]},
        ) from e
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/v1/rag/taxonomy")
async def list_taxonomy(
    app: Optional[str] = Query(None, description="filtra sub-cats por app_id"),
) -> Dict[str, Any]:
    """Devuelve taxonomy completo (4 anclas + sub-cats per-app).
    Lo usa el frontend de /admin/punto-medio y, opcionalmente,
    callers que quieran pre-cachear el set de claves válidas."""
    if app is not None and app not in VALID_APPS:
        raise HTTPException(status_code=400, detail={"error": "invalid_app"})

    conn = get_db_connection()
    if conn is None:
        raise HTTPException(status_code=503, detail={"error": "db_unavailable"})
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT category_key, category_label, parent_key "
                "FROM peaje_taxonomy WHERE is_active = TRUE ORDER BY sort_order"
            )
            canonical = cursor.fetchall() or []

            if app:
                cursor.execute(
                    """
                    SELECT app_id, canonical_category, subcategory_key,
                           subcategory_label, sort_order
                      FROM peaje_app_taxonomy
                     WHERE app_id = %s AND is_active = TRUE
                     ORDER BY canonical_category, sort_order
                    """,
                    (app,),
                )
            else:
                cursor.execute(
                    """
                    SELECT app_id, canonical_category, subcategory_key,
                           subcategory_label, sort_order
                      FROM peaje_app_taxonomy
                     WHERE is_active = TRUE
                     ORDER BY app_id, canonical_category, sort_order
                    """
                )
            sub = cursor.fetchall() or []
        return {
            "ok": True,
            "canonical": canonical,
            "subcategories": sub,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "taxonomy_query_failed", "message": str(e)[:500]},
        ) from e
    finally:
        try:
            conn.close()
        except Exception:
            pass
