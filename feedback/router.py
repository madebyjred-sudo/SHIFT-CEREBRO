"""
Cerebro feedback router.

  POST /v1/feedback        — captura cada evento del web component
                              <cerebro-feedback> en cerebro_feedback_events
                              + actualiza cache (like_count/dislike_count/
                              avg_rating) en cerebro_training_pairs si el
                              message_id existe.

  GET  /v1/feedback/stats  — agregados por message_id, opcional para el
                              admin UI de Punto Medio.

CORS abierto para los origins de las apps Shift (CL2 web, Studio web,
Eco web). El widget también funciona embed cross-origin gracias a esto.
"""
from __future__ import annotations

from typing import Optional, Literal
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config.database import get_db_connection


router = APIRouter(tags=["feedback"])


VALID_TYPES = {
    "like", "dislike", "chip", "free_text", "session_nps", "star_rating",
}
VALID_CHIPS = {
    "hallucinated", "wrong_tone", "vague", "missed_point",
    "too_long", "outdated", "perfect",
}


class FeedbackEvent(BaseModel):
    # Anchor
    message_id: Optional[str] = None
    session_id: str
    app_id: str
    tenant_id: str

    # Identity
    user_id: Optional[str] = None
    user_anonymous: bool = False

    # The signal
    feedback_type: str
    rating_value: Optional[int] = None
    chip_key: Optional[str] = None
    free_text: Optional[str] = Field(default=None, max_length=4000)

    # Context
    upstream_model: Optional[str] = None
    agent_id: Optional[str] = None
    user_agent: Optional[str] = Field(default=None, max_length=255)


@router.post("/v1/feedback")
async def post_feedback(body: FeedbackEvent):
    """Append-only insert of one feedback event. Idempotency is loose
    (per-message dedup happens client-side); duplicates here are
    cheap and don't break aggregation."""
    if body.feedback_type not in VALID_TYPES:
        raise HTTPException(400, {
            "error": "invalid_feedback_type",
            "valid": sorted(VALID_TYPES),
        })

    # Validate chip_key if feedback_type=chip
    if body.feedback_type == "chip":
        if not body.chip_key or body.chip_key not in VALID_CHIPS:
            raise HTTPException(400, {
                "error": "invalid_chip_key",
                "valid": sorted(VALID_CHIPS),
            })

    # Validate rating range
    if body.rating_value is not None:
        if body.feedback_type == "session_nps" and not (0 <= body.rating_value <= 10):
            raise HTTPException(400, {"error": "nps_out_of_range_0_10"})
        if body.feedback_type == "star_rating" and not (1 <= body.rating_value <= 5):
            raise HTTPException(400, {"error": "stars_out_of_range_1_5"})

    conn = get_db_connection()
    if conn is None:
        raise HTTPException(503, {"error": "db_unavailable"})

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO cerebro_feedback_events (
                    message_id, session_id, app_id, tenant_id,
                    user_id, user_anonymous,
                    feedback_type, rating_value, chip_key, free_text,
                    upstream_model, agent_id, user_agent
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    body.message_id,
                    body.session_id,
                    body.app_id,
                    body.tenant_id,
                    body.user_id,
                    bool(body.user_anonymous),
                    body.feedback_type,
                    body.rating_value,
                    body.chip_key,
                    body.free_text,
                    body.upstream_model,
                    body.agent_id,
                    body.user_agent,
                ),
            )
            event_id = cursor.lastrowid

            # Si hay message_id, mantener cache en cerebro_training_pairs
            # actualizado. Esto ahorra GROUP BY en queries del Punto Medio.
            if body.message_id:
                # Verificar que el row existe antes de UPDATE
                cursor.execute(
                    "SELECT id FROM cerebro_training_pairs WHERE message_id = %s",
                    (body.message_id,),
                )
                tp = cursor.fetchone()
                if tp:
                    if body.feedback_type == "like":
                        cursor.execute(
                            "UPDATE cerebro_training_pairs "
                            "SET like_count = like_count + 1, "
                            "    feedback_count = feedback_count + 1, "
                            "    quality_label = CASE "
                            "      WHEN quality_label IN ('unverified','liked') THEN 'liked' "
                            "      ELSE quality_label END "
                            "WHERE message_id = %s",
                            (body.message_id,),
                        )
                    elif body.feedback_type == "dislike":
                        cursor.execute(
                            "UPDATE cerebro_training_pairs "
                            "SET dislike_count = dislike_count + 1, "
                            "    feedback_count = feedback_count + 1, "
                            "    quality_label = CASE "
                            "      WHEN quality_label IN ('unverified','liked') THEN 'disliked' "
                            "      ELSE quality_label END "
                            "WHERE message_id = %s",
                            (body.message_id,),
                        )
                    elif body.feedback_type in ("chip", "free_text"):
                        cursor.execute(
                            "UPDATE cerebro_training_pairs "
                            "SET feedback_count = feedback_count + 1 "
                            "WHERE message_id = %s",
                            (body.message_id,),
                        )
                    elif body.feedback_type == "star_rating" and body.rating_value:
                        cursor.execute(
                            "UPDATE cerebro_training_pairs "
                            "SET feedback_count = feedback_count + 1, "
                            "    avg_rating = ((COALESCE(avg_rating,0) * feedback_count) + %s) "
                            "                 / (feedback_count + 1) "
                            "WHERE message_id = %s",
                            (body.rating_value, body.message_id),
                        )

            conn.commit()
        return {
            "status": "ok",
            "event_id": event_id,
            "message_id": body.message_id,
            "feedback_type": body.feedback_type,
            "ts": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, {"error": "feedback_insert_failed", "detail": str(e)[:300]})
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/v1/feedback/stats")
async def feedback_stats(
    app_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    days: int = 30,
):
    """Agregados de feedback para el admin UI de Punto Medio.
    Sirve para identificar agentes con muchos dislikes, chips
    recurrentes (probable bug del prompt), y tendencias NPS."""
    days = max(1, min(365, int(days)))

    conn = get_db_connection()
    if conn is None:
        raise HTTPException(503, {"error": "db_unavailable"})

    where = ["fe.created_at >= NOW() - INTERVAL %s DAY"]
    params: list = [days]
    if app_id:
        where.append("fe.app_id = %s")
        params.append(app_id)
    if tenant_id:
        where.append("fe.tenant_id = %s")
        params.append(tenant_id)
    where_sql = " AND ".join(where)

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT feedback_type, COUNT(*) as n
                FROM cerebro_feedback_events fe
                WHERE {where_sql}
                GROUP BY feedback_type
                ORDER BY n DESC
                """,
                tuple(params),
            )
            by_type = cursor.fetchall() or []

            cursor.execute(
                f"""
                SELECT chip_key, COUNT(*) as n
                FROM cerebro_feedback_events fe
                WHERE {where_sql} AND feedback_type='chip'
                GROUP BY chip_key
                ORDER BY n DESC
                """,
                tuple(params),
            )
            by_chip = cursor.fetchall() or []

            cursor.execute(
                f"""
                SELECT agent_id,
                       SUM(feedback_type='like')    AS likes,
                       SUM(feedback_type='dislike') AS dislikes,
                       COUNT(*) AS total
                FROM cerebro_feedback_events fe
                WHERE {where_sql} AND agent_id IS NOT NULL
                GROUP BY agent_id
                ORDER BY total DESC
                """,
                tuple(params),
            )
            by_agent = cursor.fetchall() or []

            cursor.execute(
                f"""
                SELECT AVG(rating_value) AS avg_nps,
                       COUNT(*) AS n
                FROM cerebro_feedback_events fe
                WHERE {where_sql} AND feedback_type='session_nps'
                """,
                tuple(params),
            )
            nps = cursor.fetchone() or {}

        return {
            "ok": True,
            "window_days": days,
            "filters": {"app_id": app_id, "tenant_id": tenant_id},
            "by_type": by_type,
            "by_chip": by_chip,
            "by_agent": by_agent,
            "nps": nps,
        }
    except Exception as e:
        raise HTTPException(500, {"error": "stats_query_failed", "detail": str(e)[:300]})
    finally:
        try:
            conn.close()
        except Exception:
            pass
