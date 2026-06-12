"""DB helpers for the viral agent — trends_detected and viral_pieces."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class ViralDB:

    # ------------------------------------------------------------------
    # trends_detected
    # ------------------------------------------------------------------

    def save_trend(
        self,
        trend_topic: str,
        platform: str,
        relevance_score: float,
        velocity: str,
        opportunity_window_hours: int,
        product: str | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO trends_detected
                        (id, trend_topic, platform, relevance_score, velocity,
                         opportunity_window_hours, product, detected_at, acted_on)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, false)
                    RETURNING id
                    """,
                    (row_id, trend_topic, platform, relevance_score, velocity,
                     opportunity_window_hours, product,
                     datetime.now(timezone.utc)),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

    def get_recent_trends(
        self,
        hours: int = 24,
        product: str | None = None,
        min_relevance: float | None = None,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                filters = ["detected_at > now() - interval '%s hours'"]
                params: list[Any] = [hours]
                if product:
                    filters.append("product = %s")
                    params.append(product)
                if min_relevance is not None:
                    filters.append("relevance_score >= %s")
                    params.append(min_relevance)
                cur.execute(
                    f"SELECT * FROM trends_detected WHERE {' AND '.join(filters)} "
                    "ORDER BY detected_at DESC",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]

    def mark_trend_acted_on(self, trend_id: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE trends_detected SET acted_on = true WHERE id = %s",
                    (trend_id,),
                )
                conn.commit()

    # ------------------------------------------------------------------
    # viral_pieces
    # ------------------------------------------------------------------

    def save_viral_piece(
        self,
        trend_id: str | None,
        product: str,
        platform: str,
        content: str,
        hook: str,
        published_at: datetime | None = None,
        engagement_score: float | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO viral_pieces
                        (id, trend_id, product, platform, content, hook,
                         published_at, engagement_score)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (row_id, trend_id, product, platform, content, hook,
                     published_at, engagement_score),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

    def get_top_pieces(
        self,
        product: str,
        days: int = 30,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM viral_pieces
                    WHERE product = %s
                      AND published_at > now() - interval '%s days'
                      AND engagement_score IS NOT NULL
                    ORDER BY engagement_score DESC
                    LIMIT %s
                    """,
                    (product, days, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    def update_engagement(self, piece_id: str, engagement_score: float) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE viral_pieces SET engagement_score = %s WHERE id = %s",
                    (engagement_score, piece_id),
                )
                conn.commit()
