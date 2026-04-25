"""Peaje Ingest — Background auto-ingestion of insights from chat."""
import json
import hashlib
from typing import List
from datetime import datetime
from config.database import get_db_connection
from graph.state import ChatMessage
from peaje.extractor import extract_insight_data_async
from pii_scrubber import full_scrub_pipeline


async def process_auto_ingest(tenant_id: str, session_id: str, agent_id: str, messages: List[ChatMessage], response: str):
    """Tarea en segundo plano para ingerir insights automáticamente."""
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
                    # Insertar insight
                    sql = """
                        INSERT INTO peaje_insights 
                        (tenant_id, session_id, agent_id, insight_text, 
                         category, sub_category, industry_vertical,
                         sentiment, confidence_score, extraction_model, pii_scrubbed,
                         source_type, anonymized_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'auto_chat', %s)
                    """
                    anonymized_hash = hashlib.sha256(f"{tenant_id}:{session_id}:{datetime.now().isoformat()}".encode()).hexdigest()
                    cursor.execute(sql, (
                        tenant_id, session_id, agent_id,
                        scrub_result["scrubbed_text"],
                        scrub_result["validated_category"],
                        scrub_result["sub_category"],
                        scrub_result["industry_vertical"],
                        insight_data["sentiment"],
                        insight_data["confidence_score"],
                        "moonshotai/kimi-k2.6",
                        scrub_result["pii_scrubbed"],
                        anonymized_hash
                    ))
                    conn.commit()
                print(f"[AUTO-INGEST] ✓ Insight guardado automáticamente para {tenant_id}")
            except Exception as db_err:
                print(f"[AUTO-INGEST DB ERROR] {db_err}")
            finally:
                conn.close()
    except Exception as e:
        print(f"[AUTO-INGEST ERROR] {e}")
