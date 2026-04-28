"""Peaje Ingest — Background auto-ingestion of insights from chat.

Post v3 multi-app: ingest is now app-aware. Callers pass `app_id`
('cl2'|'eco'|'studio'|'sentinel'); defaults to 'cl2' for back-compat
with the legacy CL2 chat path.

Flow:
  1. Extract insight (extractor.py, LLM)
  2. Scrub PII (pii_scrubber)
  3. Route via insight-router skill (decides app, sub-cat, promote)
  4. INSERT into peaje_insights with app_id
  5. Persist router decision audit row
  6. (Punto Medio consolidation runs as a separate scheduled job —
     not in this hot path; consolidation is where is_global=TRUE
     duplication happens.)
"""
import json
import hashlib
from typing import List, Optional
from datetime import datetime
from config.database import get_db_connection
from graph.state import ChatMessage
from peaje.extractor import extract_insight_data_async
from peaje.insight_router_client import route_insight
from pii_scrubber import full_scrub_pipeline


async def process_auto_ingest(
    tenant_id: str,
    session_id: str,
    agent_id: str,
    messages: List[ChatMessage],
    response: str,
    app_id: str = "cl2",
):
    """Tarea en segundo plano para ingerir insights automáticamente.

    Args:
        app_id: identifica la app Shift de origen — 'cl2' (legacy
            chat), 'eco' (GEO worker), 'studio' (creative DAG),
            'sentinel' (PR risk worker). Default 'cl2' para no
            romper callers existentes.
    """
    try:
        # Threshold: No ingerir mensajes muy cortos (evitar ruido en Punto Medio)
        last_message = messages[-1].content if messages else ""
        if len(last_message) < 20 and len(response) < 50:
            print(f"[AUTO-INGEST] Skip: Mensaje demasiado corto ({len(last_message)} chars)")
            return

        print(f"[AUTO-INGEST] Processing: Tenant={tenant_id}, Agent={agent_id}")
        
        # Reutilizar la lógica de peaje_ingest
        insight_data = await extract_insight_data_async(messages, response, tenant_id)
        
        conn = get_db_connection()
        tenant_industry = None
        if conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT industry_vertical FROM peaje_tenants WHERE tenant_id = %s", (tenant_id,))
                    row = cursor.fetchone()
                    if row: tenant_industry = row.get("industry_vertical")
            except Exception: pass

        scrub_result = full_scrub_pipeline(
            insight_text=insight_data["insight_text"],
            raw_category=insight_data["category"],
            tenant_industry=tenant_industry,
            conversation_text=json.dumps([{"role": m.role, "content": m.content} for m in messages]) + f"\nASSISTANT: {response}",
        )

        if conn:
            try:
                with conn.cursor() as cursor:
                    # Insertar insight con app_id (v3). Si la columna
                    # no existe (migración aún no aplicada), el INSERT
                    # cae al except de abajo y reintentamos sin app_id
                    # para no bloquear a callers en deploys parciales.
                    sql_v3 = """
                        INSERT INTO peaje_insights
                        (app_id, tenant_id, session_id, agent_id, insight_text,
                         category, sub_category, industry_vertical,
                         sentiment, confidence_score, extraction_model, pii_scrubbed,
                         source_type, anonymized_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'auto_chat', %s)
                    """
                    anonymized_hash = hashlib.sha256(
                        f"{tenant_id}:{session_id}:{datetime.now().isoformat()}".encode()
                    ).hexdigest()
                    insight_id = None
                    try:
                        cursor.execute(sql_v3, (
                            app_id,
                            tenant_id, session_id, agent_id,
                            scrub_result["scrubbed_text"],
                            scrub_result["validated_category"],
                            scrub_result["sub_category"],
                            scrub_result["industry_vertical"],
                            insight_data["sentiment"],
                            insight_data["confidence_score"],
                            "moonshotai/kimi-k2.6",
                            scrub_result["pii_scrubbed"],
                            anonymized_hash,
                        ))
                        insight_id = cursor.lastrowid
                    except Exception as v3_err:
                        # Fallback a v2 (sin app_id) si la columna falta.
                        print(f"[AUTO-INGEST] v3 INSERT falló ({v3_err}); fallback a v2 sin app_id")
                        sql_v2 = """
                            INSERT INTO peaje_insights
                            (tenant_id, session_id, agent_id, insight_text,
                             category, sub_category, industry_vertical,
                             sentiment, confidence_score, extraction_model, pii_scrubbed,
                             source_type, anonymized_hash)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'auto_chat', %s)
                        """
                        cursor.execute(sql_v2, (
                            tenant_id, session_id, agent_id,
                            scrub_result["scrubbed_text"],
                            scrub_result["validated_category"],
                            scrub_result["sub_category"],
                            scrub_result["industry_vertical"],
                            insight_data["sentiment"],
                            insight_data["confidence_score"],
                            "moonshotai/kimi-k2.6",
                            scrub_result["pii_scrubbed"],
                            anonymized_hash,
                        ))
                        insight_id = cursor.lastrowid
                    conn.commit()
                print(f"[AUTO-INGEST] ✓ Insight guardado (app={app_id}, id={insight_id}) para {tenant_id}")

                # Routing post-INSERT — best-effort. La decisión queda
                # en peaje_router_decisions; la consolidación a Punto
                # Medio (con is_global=TRUE si promote) la hace un job
                # separado.
                if insight_id is not None:
                    try:
                        await route_insight(
                            insight_id=insight_id,
                            source_app=app_id,
                            tenant_id=tenant_id,
                            industry_vertical=scrub_result.get("industry_vertical") or tenant_industry,
                            insight_text=scrub_result["scrubbed_text"],
                            extraction_model="moonshotai/kimi-k2.6",
                            session_type="chat",
                            tenant_metadata=None,
                        )
                    except Exception as route_err:
                        print(f"[AUTO-INGEST ROUTER ERROR] {route_err}")
            except Exception as db_err:
                print(f"[AUTO-INGEST DB ERROR] {db_err}")
            finally:
                conn.close()
    except Exception as e:
        print(f"[AUTO-INGEST ERROR] {e}")
