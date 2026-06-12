"""
Research DB — competitor_snapshots, market_signals, feature_gaps tables.
"""

from __future__ import annotations

from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class ResearchDB:

    # ------------------------------------------------------------------
    # competitor_snapshots
    # ------------------------------------------------------------------

    def save_snapshot(
        self,
        product: str,
        competitor: str,
        changes_detected: bool,
        summary: str,
        raw_content: str = "",
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO competitor_snapshots
                        (product, competitor, changes_detected, summary, raw_content)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (product, competitor, changes_detected, summary, raw_content),
                )
                row = cur.fetchone()
        return str(row["id"])

    def get_latest_snapshot(
        self,
        product: str,
        competitor: str,
    ) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM competitor_snapshots
                    WHERE product = %s AND competitor = %s
                    ORDER BY snapshot_date DESC
                    LIMIT 1
                    """,
                    (product, competitor),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def list_snapshots(
        self,
        product: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM competitor_snapshots
                    WHERE product = %s
                    ORDER BY snapshot_date DESC
                    LIMIT %s
                    """,
                    (product, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # market_signals
    # ------------------------------------------------------------------

    def save_signal(
        self,
        product: str,
        source: str,
        headline: str,
        relevance_score: int,
        url: str = "",
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO market_signals
                        (product, source, headline, relevance_score, url)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (product, source, headline, relevance_score, url),
                )
                row = cur.fetchone()
        return str(row["id"])

    def list_signals(
        self,
        product: str,
        min_relevance: int = 7,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM market_signals
                    WHERE product = %s AND relevance_score >= %s
                    ORDER BY detected_at DESC
                    LIMIT %s
                    """,
                    (product, min_relevance, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_sentiment_inputs(self, product: str) -> dict[str, list[str]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT body FROM support_tickets
                    WHERE product = %s AND status = 'resolved'
                    ORDER BY resolved_at DESC LIMIT 100
                    """,
                    (product,),
                )
                tickets = [r["body"] for r in cur.fetchall()]

                cur.execute(
                    "SELECT comment FROM nps_responses WHERE product = %s AND comment != '' LIMIT 100",
                    (product,),
                )
                nps_comments = [r["comment"] for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT review_text FROM reviews
                    WHERE product = %s ORDER BY review_date DESC LIMIT 100
                    """,
                    (product,),
                )
                review_text = [r["review_text"] for r in cur.fetchall()]

        return {"tickets": tickets, "nps_comments": nps_comments, "review_text": review_text}

    # ------------------------------------------------------------------
    # feature_gaps
    # ------------------------------------------------------------------

    def save_feature_gap(
        self,
        product: str,
        feature: str,
        competitor_coverage: int,
        customer_demand_score: int,
        status: str = "proposed",
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO feature_gaps
                        (product, feature, competitor_coverage, customer_demand_score, status)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (product, feature) DO UPDATE SET
                        competitor_coverage = EXCLUDED.competitor_coverage,
                        customer_demand_score = EXCLUDED.customer_demand_score,
                        status = EXCLUDED.status
                    RETURNING id
                    """,
                    (product, feature, competitor_coverage, customer_demand_score, status),
                )
                row = cur.fetchone()
        return str(row["id"])

    def list_feature_gaps(
        self,
        product: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if status:
                    cur.execute(
                        "SELECT * FROM feature_gaps WHERE product = %s AND status = %s ORDER BY customer_demand_score DESC",
                        (product, status),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM feature_gaps WHERE product = %s ORDER BY customer_demand_score DESC",
                        (product,),
                    )
                return [dict(r) for r in cur.fetchall()]
