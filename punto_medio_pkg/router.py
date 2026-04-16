"""Punto Medio Router — FastAPI endpoints for consolidation, RAG, and review."""
from typing import List
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.database import get_db_connection
from config.models import get_llm
from punto_medio import (
    get_dynamic_rag,
    consolidate_punto_medio,
)

punto_medio_router = APIRouter(tags=["punto_medio"])


@punto_medio_router.post("/punto-medio/consolidate")
async def consolidate_endpoint():
    """Trigger Punto Medio consolidation job.
    In production, this should be called by a cron job every 6 hours.
    Can also be triggered manually for immediate refresh."""
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        result = await consolidate_punto_medio(conn, llm_func=get_llm('minimax/minimax-m2.5'))
        return result
    finally:
        conn.close()


@punto_medio_router.get("/punto-medio/rag/{tenant_id}")
async def get_rag_for_tenant(tenant_id: str):
    """Get the dynamic RAG injection text for a specific tenant.
    Shows what would be injected into system prompts.
    Useful for debugging and transparency."""
    conn = get_db_connection()
    try:
        rag = get_dynamic_rag(conn, tenant_id)
        return {
            "tenant_id": tenant_id,
            "global_rag_length": len(rag["global_rag"]),
            "tenant_rag_length": len(rag["tenant_rag"]),
            "patterns_rag_length": len(rag["patterns_rag"]),
            "combined_rag_length": len(rag["combined_rag"]),
            "global_rag": rag["global_rag"],
            "tenant_rag": rag["tenant_rag"],
            "patterns_rag": rag["patterns_rag"],
        }
    finally:
        if conn:
            conn.close()


@punto_medio_router.get("/punto-medio/review")
async def get_pending_reviews():
    """Get all pending consolidations and patterns awaiting review.
    Returns items that are 'grey' (pending) — not yet injected into RAG."""
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        with conn.cursor() as cursor:
            # Pending consolidations
            cursor.execute("""
                SELECT id, scope, tenant_id, category, industry_vertical,
                       consolidated_text, executive_brief,
                       source_insight_count, contributing_tenants, confidence_score,
                       approval_status, version, last_consolidated_at, created_at
                FROM punto_medio_consolidated
                WHERE approval_status = 'pending' AND is_active = TRUE
                ORDER BY last_consolidated_at DESC
            """)
            pending_consolidations = cursor.fetchall()
            
            # Pending patterns
            cursor.execute("""
                SELECT id, pattern_type, category, pattern_text,
                       industry_vertical, region, occurrence_count,
                       source_insight_count, confidence_score,
                       approval_status, first_seen_at, last_seen_at
                FROM peaje_patterns
                WHERE approval_status = 'pending' AND is_active = TRUE
                ORDER BY last_seen_at DESC
            """)
            pending_patterns = cursor.fetchall()
        
        # Convert datetime objects for JSON serialization
        for item in pending_consolidations + pending_patterns:
            for key, val in item.items():
                if hasattr(val, 'isoformat'):
                    item[key] = val.isoformat()
                elif isinstance(val, __import__('decimal').Decimal):
                    item[key] = float(val)
        
        return {
            "pending_consolidations": pending_consolidations,
            "pending_consolidations_count": len(pending_consolidations),
            "pending_patterns": pending_patterns,
            "pending_patterns_count": len(pending_patterns),
        }
    finally:
        conn.close()


class ReviewAction(BaseModel):
    action: str  # "approve" or "reject"
    reviewed_by: str = "admin"
    item_type: str = "consolidation"  # "consolidation" or "pattern"


@punto_medio_router.patch("/punto-medio/review/{item_id}")
async def review_item(item_id: int, review: ReviewAction):
    """Approve or reject a pending consolidation or pattern.
    Approved items become 'green' and get injected into live RAG.
    Rejected items stay in DB but never get injected."""
    if review.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")
    
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database not available")
    
    new_status = "approved" if review.action == "approve" else "rejected"
    
    try:
        with conn.cursor() as cursor:
            if review.item_type == "consolidation":
                cursor.execute("""
                    UPDATE punto_medio_consolidated
                    SET approval_status = %s, reviewed_by = %s, reviewed_at = NOW()
                    WHERE id = %s
                """, (new_status, review.reviewed_by, item_id))
            elif review.item_type == "pattern":
                cursor.execute("""
                    UPDATE peaje_patterns
                    SET approval_status = %s, reviewed_by = %s, reviewed_at = NOW()
                    WHERE id = %s
                """, (new_status, review.reviewed_by, item_id))
            else:
                raise HTTPException(status_code=400, detail="item_type must be 'consolidation' or 'pattern'")
            
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Item {item_id} not found")
            
            conn.commit()
        
        return {
            "status": "updated",
            "item_id": item_id,
            "item_type": review.item_type,
            "new_status": new_status,
            "reviewed_by": review.reviewed_by,
            "timestamp": datetime.now().isoformat(),
        }
    finally:
        conn.close()


@punto_medio_router.post("/punto-medio/review/bulk")
async def bulk_review(item_ids: List[int], action: str = "approve", reviewed_by: str = "admin", item_type: str = "consolidation"):
    """Bulk approve or reject multiple items at once."""
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")
    
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database not available")
    
    new_status = "approved" if action == "approve" else "rejected"
    
    try:
        with conn.cursor() as cursor:
            table = "punto_medio_consolidated" if item_type == "consolidation" else "peaje_patterns"
            placeholders = ", ".join(["%s"] * len(item_ids))
            cursor.execute(f"""
                UPDATE {table}
                SET approval_status = %s, reviewed_by = %s, reviewed_at = NOW()
                WHERE id IN ({placeholders})
            """, [new_status, reviewed_by] + item_ids)
            
            updated = cursor.rowcount
            conn.commit()
        
        return {
            "status": "bulk_updated",
            "updated_count": updated,
            "action": action,
            "reviewed_by": reviewed_by,
            "timestamp": datetime.now().isoformat(),
        }
    finally:
        conn.close()
