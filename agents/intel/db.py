"""Intel DB — intel_signals and keyword_trends tables."""

from __future__ import annotations

from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class IntelDB:

    def save_signal(
        self,
        signal_type: str,
        headline: str,
        product: str = "",
        competitor: str = "",
        relevance_score: int = 5,
        summary: str = "",
        source_url: str = "",
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO intel_signals
                        (signal_type, headline, product, competitor, relevance_score, summary, source_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                    """,
                    (signal_type, headline, product, competitor, relevance_score, summary, source_url),
                )
                return str(cur.fetchone()["id"])

    def list_signals(self, product: str = "", min_relevance: int = 6, limit: int = 50) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if product:
                    cur.execute(
                        """
                        SELECT * FROM intel_signals
                        WHERE product = %s AND relevance_score >= %s
                        ORDER BY detected_at DESC LIMIT %s
                        """,
                        (product, min_relevance, limit),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM intel_signals WHERE relevance_score >= %s ORDER BY detected_at DESC LIMIT %s",
                        (min_relevance, limit),
                    )
                return [dict(r) for r in cur.fetchall()]

    def upsert_keyword_trend(self, keyword: str, product: str, trend_direction: str, volume_index: int) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO keyword_trends (keyword, product, trend_direction, volume_index)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (keyword, product) DO UPDATE SET
                        trend_direction = EXCLUDED.trend_direction,
                        volume_index    = EXCLUDED.volume_index,
                        checked_at      = NOW()
                    """,
                    (keyword, product, trend_direction, volume_index),
                )

    def list_keyword_trends(self, product: str, direction: str | None = None) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if direction:
                    cur.execute(
                        "SELECT * FROM keyword_trends WHERE product = %s AND trend_direction = %s ORDER BY volume_index DESC",
                        (product, direction),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM keyword_trends WHERE product = %s ORDER BY volume_index DESC",
                        (product,),
                    )
                return [dict(r) for r in cur.fetchall()]
