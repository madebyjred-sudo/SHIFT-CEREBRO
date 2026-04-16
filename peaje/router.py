"""Peaje Router — FastAPI endpoints for El Peaje insight ingestion flywheel."""
import json
import hashlib
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.database import get_db_connection
from graph.state import ChatMessage
from peaje.extractor import extract_insight_data_async
from pii_scrubber import full_scrub_pipeline, check_deduplication

peaje_router = APIRouter(tags=["peaje"])


# ═══════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════

class PeajeIngestRequest(BaseModel):
    tenantId: str
    sessionId: str
    agentId: str
    messages: List[ChatMessage]
    response: str


class PeajeDebateIngestRequest(BaseModel):
    tenantId: str
    sessionId: str
    agentA: str
    agentB: str
    topic: str
    transcript: List[Dict[str, Any]]
    synthesis: str


class NodeMetrics(BaseModel):
    tokens: Optional[int] = 0
    time_ms: Optional[int] = 0
    user_rating: Optional[int] = 0


class ExecutedNode(BaseModel):
    node_id: str
    agent: str
    prompt: Optional[str] = ""
    output_text: str
    metrics: Optional[NodeMetrics] = None


class NodeExecutionPayload(BaseModel):
    session_id: str
    client_id: str
    tenant_id: str = "shift"
    telemetry: Dict[str, Any]
    executed_nodes: List[ExecutedNode]


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@peaje_router.post("/peaje/ingest")
async def peaje_ingest(request: PeajeIngestRequest):
    """Ingesta asíncrona hacia el Flywheel (El Peaje) — v2.0 con PII Scrubber + Taxonomy Validation"""
    extraction_start = time.time()
    try:
        print(f"[EL PEAJE v2] Processing: Tenant={request.tenantId}, Agent={request.agentId}")
        
        # Generate hashes for anonymization & deduplication
        conversation_text = json.dumps([{"role": m.role, "content": m.content} for m in request.messages])
        anonymized_hash = hashlib.sha256(f"{request.tenantId}:{request.sessionId}:{datetime.now().isoformat()}".encode()).hexdigest()
        conversation_hash = hashlib.sha256(conversation_text.encode()).hexdigest()

        # Get database connection
        conn = get_db_connection()
        
        # ═══ DEDUPLICATION CHECK ═══
        if conn and check_deduplication(conversation_hash, conn):
            print(f"[EL PEAJE v2] Duplicate detected, skipping: {conversation_hash[:16]}...")
            if conn:
                conn.close()
            return {"status": "deduplicated", "tenant": request.tenantId, "conversation_hash": conversation_hash[:16]}
        
        # ═══ STEP 1: LLM Extraction (Layer 1 — Probabilistic) ═══
        insight_data = await extract_insight_data_async(request.messages, request.response, request.tenantId)
        
        # ═══ STEP 2: PII Scrubber (Layer 2 — Deterministic) ═══
        tenant_industry = None
        if conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT industry_vertical FROM peaje_tenants WHERE tenant_id = %s", (request.tenantId,))
                    tenant_row = cursor.fetchone()
                    if tenant_row:
                        tenant_industry = tenant_row.get("industry_vertical")
            except Exception:
                pass
        
        scrub_result = full_scrub_pipeline(
            insight_text=insight_data["insight_text"],
            raw_category=insight_data["category"],
            tenant_industry=tenant_industry,
            conversation_text=conversation_text,
        )
        
        extraction_duration_ms = int((time.time() - extraction_start) * 1000)
        extraction_model = "minimax/minimax-m2.5"
        
        print(f"[EL PEAJE v2] PII Scrubbed: {scrub_result['total_pii_scrubbed']} items | "
              f"Category: {scrub_result['original_category']} → {scrub_result['validated_category']} "
              f"(valid={scrub_result['category_was_valid']}) | "
              f"Industry: {scrub_result['industry_vertical']}")
        
        if conn:
            try:
                with conn.cursor() as cursor:
                    # ═══ STEP 3: Insert insight with v2.0 schema ═══
                    sql = """
                        INSERT INTO peaje_insights 
                        (tenant_id, session_id, agent_id, insight_text, 
                         category, sub_category, industry_vertical,
                         sentiment, confidence_score, extraction_model, pii_scrubbed,
                         source_type, anonymized_hash, raw_conversation_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (
                        request.tenantId,
                        request.sessionId,
                        request.agentId,
                        scrub_result["scrubbed_text"],
                        scrub_result["validated_category"],
                        scrub_result["sub_category"],
                        scrub_result["industry_vertical"],
                        insight_data["sentiment"],
                        insight_data["confidence_score"],
                        extraction_model,
                        scrub_result["pii_scrubbed"],
                        "chat",
                        anonymized_hash,
                        conversation_hash
                    ))
                    insight_id = cursor.lastrowid
                    
                    # ═══ STEP 4: Update session tracking ═══
                    session_sql = """
                        INSERT INTO peaje_sessions 
                        (tenant_id, session_id, message_count, insight_count, agents_used, source, debate_mode)
                        VALUES (%s, %s, %s, 1, %s, %s, FALSE)
                        ON DUPLICATE KEY UPDATE
                        message_count = message_count + %s,
                        insight_count = insight_count + 1,
                        agents_used = JSON_MERGE_PATCH(COALESCE(agents_used, '[]'), %s)
                    """
                    agents_json = json.dumps([request.agentId])
                    cursor.execute(session_sql, (
                        request.tenantId,
                        request.sessionId,
                        len(request.messages),
                        agents_json,
                        "embed" if "embed" in request.sessionId else "standalone",
                        len(request.messages),
                        agents_json
                    ))
                    
                    # ═══ STEP 5: Log extraction audit trail ═══
                    log_sql = """
                        INSERT INTO peaje_extraction_log
                        (insight_id, tenant_id, session_id, extraction_model, extraction_duration_ms,
                         pii_items_scrubbed, pii_types_found, extraction_status, category_validated,
                         original_category, input_message_count, input_char_count, conversation_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(log_sql, (
                        insight_id,
                        request.tenantId,
                        request.sessionId,
                        extraction_model,
                        extraction_duration_ms,
                        scrub_result["total_pii_scrubbed"],
                        json.dumps(scrub_result["pii_counts"]),
                        "success",
                        scrub_result["category_was_valid"],
                        scrub_result["original_category"],
                        len(request.messages),
                        len(conversation_text),
                        conversation_hash
                    ))
                    
                    conn.commit()
                    
                print(f"[EL PEAJE v2] ✓ Insight saved ID:{insight_id} | "
                      f"PII:{scrub_result['total_pii_scrubbed']} | "
                      f"Cat:{scrub_result['validated_category']} | "
                      f"{extraction_duration_ms}ms")
                
                return {
                    "status": "ingested",
                    "version": "v2.0",
                    "tenant": request.tenantId,
                    "insight_id": insight_id,
                    "category": scrub_result["validated_category"],
                    "sub_category": scrub_result["sub_category"],
                    "industry_vertical": scrub_result["industry_vertical"],
                    "sentiment": insight_data["sentiment"],
                    "confidence_score": insight_data["confidence_score"],
                    "pii_scrubbed": scrub_result["pii_scrubbed"],
                    "pii_items_removed": scrub_result["total_pii_scrubbed"],
                    "category_validated": scrub_result["category_was_valid"],
                    "extraction_ms": extraction_duration_ms,
                    "timestamp": datetime.now().isoformat()
                }
                
            except Exception as db_error:
                conn.rollback()
                print(f"[EL PEAJE v2 DB ERROR] {db_error}")
                return {
                    "status": "logged_only",
                    "tenant": request.tenantId,
                    "error": str(db_error),
                    "category": scrub_result["validated_category"],
                    "sentiment": insight_data["sentiment"]
                }
            finally:
                conn.close()
        else:
            print(f"[EL PEAJE v2] Database not available, logged only")
            return {
                "status": "logged_only",
                "tenant": request.tenantId,
                "category": scrub_result["validated_category"],
                "sentiment": insight_data["sentiment"],
                "note": "Database connection not available"
            }
            
    except Exception as e:
        print(f"[EL PEAJE v2 ERROR] {e}")
        return {"status": "error", "message": str(e)}


@peaje_router.post("/peaje/ingest-debate")
async def peaje_ingest_debate(request: PeajeDebateIngestRequest):
    """Ingest a debate transcript into the Peaje — extracts multiple insights from the rich strategic content."""
    try:
        print(f"[EL PEAJE v2 DEBATE] Processing debate: {request.agentA} vs {request.agentB} on '{request.topic[:40]}...'")
        
        insights_saved = 0
        errors = []
        
        # Process each turn of the debate as a separate insight
        for i, turn in enumerate(request.transcript):
            try:
                turn_content = turn.get("content", "")
                turn_agent = turn.get("agent", "debate_judge")
                
                if not turn_content or len(turn_content) < 20:
                    continue
                
                synthetic_messages = [
                    ChatMessage(role="user", content=f"DEBATE TOPIC: {request.topic}"),
                    ChatMessage(role="assistant", content=turn_content),
                ]
                
                insight_data = await extract_insight_data_async(synthetic_messages, turn_content, request.tenantId)
                
                scrub_result = full_scrub_pipeline(
                    insight_text=insight_data["insight_text"],
                    raw_category=insight_data["category"],
                    conversation_text=turn_content,
                )
                
                conn = get_db_connection()
                if conn:
                    try:
                        conversation_hash = hashlib.sha256(f"{request.sessionId}:turn{i}:{turn_content[:100]}".encode()).hexdigest()
                        anonymized_hash = hashlib.sha256(f"{request.tenantId}:{request.sessionId}:debate:{i}".encode()).hexdigest()
                        
                        with conn.cursor() as cursor:
                            cursor.execute("""
                                INSERT INTO peaje_insights 
                                (tenant_id, session_id, agent_id, insight_text, 
                                 category, sub_category, industry_vertical,
                                 sentiment, confidence_score, extraction_model, pii_scrubbed,
                                 source_type, debate_turn, anonymized_hash, raw_conversation_hash)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                request.tenantId,
                                request.sessionId,
                                turn_agent,
                                scrub_result["scrubbed_text"],
                                scrub_result["validated_category"],
                                scrub_result["sub_category"],
                                scrub_result["industry_vertical"],
                                insight_data["sentiment"],
                                insight_data["confidence_score"],
                                "minimax/minimax-m2.5",
                                scrub_result["pii_scrubbed"],
                                "debate",
                                i + 1,
                                anonymized_hash,
                                conversation_hash
                            ))
                            
                            cursor.execute("""
                                INSERT INTO peaje_sessions 
                                (tenant_id, session_id, message_count, insight_count, agents_used, source, debate_mode)
                                VALUES (%s, %s, 1, 1, %s, 'standalone', TRUE)
                                ON DUPLICATE KEY UPDATE
                                    message_count = message_count + 1,
                                    insight_count = insight_count + 1,
                                    debate_mode = TRUE
                            """, (
                                request.tenantId,
                                request.sessionId,
                                json.dumps([request.agentA, request.agentB]),
                            ))
                        
                        conn.commit()
                        insights_saved += 1
                    except Exception as db_err:
                        errors.append(f"Turn {i}: {str(db_err)}")
                    finally:
                        conn.close()
                        
            except Exception as turn_err:
                errors.append(f"Turn {i}: {str(turn_err)}")
        
        # Also extract an insight from the judge's synthesis
        if request.synthesis and len(request.synthesis) > 20:
            try:
                synth_messages = [
                    ChatMessage(role="user", content=f"DEBATE SYNTHESIS: {request.topic}"),
                    ChatMessage(role="assistant", content=request.synthesis),
                ]
                synth_data = await extract_insight_data_async(synth_messages, request.synthesis, request.tenantId)
                synth_scrub = full_scrub_pipeline(
                    insight_text=synth_data["insight_text"],
                    raw_category=synth_data["category"],
                    conversation_text=request.synthesis,
                )
                
                conn = get_db_connection()
                if conn:
                    try:
                        with conn.cursor() as cursor:
                            cursor.execute("""
                                INSERT INTO peaje_insights 
                                (tenant_id, session_id, agent_id, insight_text, 
                                 category, sub_category, industry_vertical,
                                 sentiment, confidence_score, extraction_model, pii_scrubbed,
                                 source_type, anonymized_hash, raw_conversation_hash)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                request.tenantId,
                                request.sessionId,
                                "debate_judge",
                                synth_scrub["scrubbed_text"],
                                synth_scrub["validated_category"],
                                synth_scrub["sub_category"],
                                synth_scrub["industry_vertical"],
                                synth_data["sentiment"],
                                min(synth_data["confidence_score"] + 0.10, 0.99),
                                "minimax/minimax-m2.5",
                                synth_scrub["pii_scrubbed"],
                                "debate",
                                hashlib.sha256(f"{request.tenantId}:{request.sessionId}:synthesis".encode()).hexdigest(),
                                hashlib.sha256(request.synthesis[:200].encode()).hexdigest(),
                            ))
                        conn.commit()
                        insights_saved += 1
                    except Exception as synth_db_err:
                        errors.append(f"Synthesis: {str(synth_db_err)}")
                    finally:
                        conn.close()
            except Exception as synth_err:
                errors.append(f"Synthesis: {str(synth_err)}")
        
        print(f"[EL PEAJE v2 DEBATE] ✓ {insights_saved} insights saved from debate | Errors: {len(errors)}")
        
        return {
            "status": "ingested",
            "version": "v2.0",
            "source": "debate",
            "tenant": request.tenantId,
            "insights_saved": insights_saved,
            "turns_processed": len(request.transcript),
            "errors": errors[:5] if errors else [],
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"[EL PEAJE v2 DEBATE ERROR] {e}")
        return {"status": "error", "message": str(e)}


@peaje_router.post("/peaje/nodes")
async def peaje_nodes(request: NodeExecutionPayload):
    """Ingesta asíncrona dedicada para la ejecución de Nodos (Dual Ingestion v2.0)."""
    try:
        print(f"[EL PEAJE v2 NODES] Processing session: {request.session_id} | Nodes: {len(request.executed_nodes)}")

        insights_saved = 0
        node_output_records = []
        errors = []

        # ── PASO 1: Insertar registro maestro de ejecución ──────────────
        conn_exec = get_db_connection()
        execution_db_id = None
        if conn_exec:
            try:
                telemetry = request.telemetry or {}
                with conn_exec.cursor() as cur:
                    cur.execute("""
                        INSERT INTO peaje_node_executions
                        (execution_id, session_id, tenant_id, client_id,
                         total_time_ms, user_interventions, node_count,
                         nodes_succeeded, nodes_failed, status, insights_saved)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            updated_at = NOW()
                    """, (
                        request.session_id,
                        request.session_id,
                        request.tenant_id,
                        request.client_id,
                        telemetry.get("total_time_ms", 0),
                        telemetry.get("user_interventions", 0),
                        len(request.executed_nodes),
                        0,
                        0,
                        "processing",
                        0,
                    ))
                    execution_db_id = conn_exec.insert_id()
                conn_exec.commit()
            except Exception as exec_err:
                print(f"[PEAJE NODES] Error inserting execution record: {exec_err}")
                errors.append(f"execution_record: {str(exec_err)}")
            finally:
                conn_exec.close()

        # ── PASO 2: Marcar sesión como nodes_mode=TRUE ───────────────────
        conn_sess = get_db_connection()
        if conn_sess:
            try:
                with conn_sess.cursor() as cur:
                    cur.execute("""
                        INSERT INTO peaje_sessions
                        (tenant_id, session_id, nodes_mode, nodes_executions, source)
                        VALUES (%s, %s, TRUE, 1, 'nodes_canvas')
                        ON DUPLICATE KEY UPDATE
                            nodes_mode = TRUE,
                            nodes_executions = COALESCE(nodes_executions, 0) + 1,
                            message_count = message_count + %s
                    """, (
                        request.tenant_id,
                        request.session_id,
                        len(request.executed_nodes),
                    ))
                conn_sess.commit()
            except Exception as sess_err:
                print(f"[PEAJE NODES] Session upsert error (migration needed?): {sess_err}")
            finally:
                conn_sess.close()

        # ── PASO 3: Procesar cada nodo (insight + telemetría por nodo) ───
        for node_order, node in enumerate(request.executed_nodes):
            try:
                if not node.output_text or len(node.output_text) < 20:
                    node_output_records.append((node, node_order, None))
                    continue

                prompt_text = node.prompt if node.prompt else "Ejecuta tu rol de especialista."
                synthetic_messages = [
                    ChatMessage(role="user", content=prompt_text),
                ]

                insight_data = await extract_insight_data_async(synthetic_messages, node.output_text, request.tenant_id)

                scrub_result = full_scrub_pipeline(
                    insight_text=insight_data["insight_text"],
                    raw_category=insight_data["category"],
                    conversation_text=node.output_text,
                )

                conn_node = get_db_connection()
                insight_id = None
                if conn_node:
                    try:
                        conversation_hash = hashlib.sha256(
                            f"{request.session_id}:{node.node_id}:{node.output_text[:100]}".encode()
                        ).hexdigest()
                        anonymized_hash = hashlib.sha256(
                            f"{request.tenant_id}:{request.session_id}:node:{node.node_id}".encode()
                        ).hexdigest()
                        prompt_hash = hashlib.sha256(prompt_text.encode()).hexdigest() if prompt_text else None
                        metrics = node.metrics or NodeMetrics()

                        with conn_node.cursor() as cursor:
                            cursor.execute("""
                                INSERT INTO peaje_insights
                                (tenant_id, session_id, agent_id, insight_text,
                                 category, sub_category, industry_vertical,
                                 sentiment, confidence_score, extraction_model, pii_scrubbed,
                                 source_type, anonymized_hash, raw_conversation_hash)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                request.tenant_id,
                                request.session_id,
                                node.agent,
                                scrub_result["scrubbed_text"],
                                scrub_result["validated_category"],
                                scrub_result["sub_category"],
                                scrub_result["industry_vertical"],
                                insight_data["sentiment"],
                                insight_data["confidence_score"],
                                "minimax/minimax-m2.5",
                                scrub_result["pii_scrubbed"],
                                "nodes_canvas",
                                anonymized_hash,
                                conversation_hash,
                            ))
                            insight_id = conn_node.insert_id()

                            cursor.execute("""
                                INSERT INTO peaje_node_outputs
                                (execution_id, tenant_id, session_id,
                                 node_id, agent_id, node_order,
                                 prompt_hash, prompt_preview,
                                 output_chars, output_quality,
                                 tokens_used, time_ms, user_rating, insight_id)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                request.session_id,
                                request.tenant_id,
                                request.session_id,
                                node.node_id,
                                node.agent,
                                node_order,
                                prompt_hash,
                                prompt_text[:500] if prompt_text else None,
                                len(node.output_text),
                                insight_data.get("confidence_score", None),
                                metrics.tokens or 0,
                                metrics.time_ms or 0,
                                metrics.user_rating or 0,
                                insight_id,
                            ))

                        conn_node.commit()
                        insights_saved += 1
                        node_output_records.append((node, node_order, insight_id))

                    except Exception as node_db_err:
                        errors.append(f"Node {node.node_id} DB: {str(node_db_err)}")
                        conn_node.rollback()
                    finally:
                        conn_node.close()

            except Exception as node_err:
                errors.append(f"Node {node.node_id}: {str(node_err)}")

        # ── PASO 4: Actualizar registro de ejecución con resultados ──────
        conn_update = get_db_connection()
        if conn_update:
            try:
                with conn_update.cursor() as cur:
                    cur.execute("""
                        UPDATE peaje_node_executions
                        SET insights_saved  = %s,
                            nodes_succeeded = %s,
                            nodes_failed    = %s,
                            status          = %s
                        WHERE execution_id = %s
                    """, (
                        insights_saved,
                        insights_saved,
                        len(request.executed_nodes) - insights_saved,
                        "completed" if not errors else "partial",
                        request.session_id,
                    ))
                conn_update.commit()
            except Exception as upd_err:
                print(f"[PEAJE NODES] Error updating execution record: {upd_err}")
            finally:
                conn_update.close()

        print(f"[EL PEAJE v2 NODES] ✓ {insights_saved}/{len(request.executed_nodes)} nodes saved | Errors: {len(errors)}")

        return {
            "status": "ingested",
            "version": "v2.0",
            "source": "nodes_canvas",
            "tenant": request.tenant_id,
            "insights_saved": insights_saved,
            "nodes_processed": len(request.executed_nodes),
            "telemetry": request.telemetry,
            "errors": errors[:5] if errors else [],
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        print(f"[EL PEAJE v2 NODES ERROR] {e}")
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════
# HEALTH & INSIGHTS ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@peaje_router.get("/peaje/health")
async def peaje_health():
    """Get health and statistics from the Peaje/Punto Medio system."""
    from punto_medio import get_peaje_stats
    conn = get_db_connection()
    try:
        stats = get_peaje_stats(conn)
        return stats
    finally:
        if conn:
            conn.close()


@peaje_router.get("/peaje/insights/{tenant_id}")
async def peaje_insights_for_tenant(tenant_id: str):
    """Get insights summary for a specific tenant.
    STRICT MULTI-TENANT ISOLATION: Only returns data for the specified tenant."""
    from punto_medio import get_tenant_insights_summary
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        summary = get_tenant_insights_summary(conn, tenant_id)
        return summary
    finally:
        conn.close()
