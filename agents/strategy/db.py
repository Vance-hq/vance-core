"""Strategy DB — strategic_plans and strategy_signals tables."""

from __future__ import annotations

import json
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class StrategyDB:

    def upsert_plan(self, product: str, quarter: str, okrs: list, growth_levers: list, status: str = "draft") -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO strategic_plans (product, quarter, okrs, growth_levers, status)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (product, quarter) DO UPDATE SET
                        okrs = EXCLUDED.okrs,
                        growth_levers = EXCLUDED.growth_levers,
                        status = EXCLUDED.status
                    RETURNING id
                    """,
                    (product, quarter, json.dumps(okrs), json.dumps(growth_levers), status),
                )
                return str(cur.fetchone()["id"])

    def get_plan(self, product: str, quarter: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM strategic_plans WHERE product = %s AND quarter = %s",
                    (product, quarter),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def save_signal(self, product: str, signal_type: str, summary: str, recommendation: str, source_agent: str) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO strategy_signals (product, signal_type, summary, recommendation, source_agent)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                    """,
                    (product, signal_type, summary, recommendation, source_agent),
                )
                return str(cur.fetchone()["id"])

    def list_signals(self, product: str, actioned: bool = False, limit: int = 20) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM strategy_signals WHERE product = %s AND actioned = %s ORDER BY created_at DESC LIMIT %s",
                    (product, actioned, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    def mark_signal_actioned(self, signal_id: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE strategy_signals SET actioned = TRUE WHERE id = %s", (signal_id,))

    # ------------------------------------------------------------------
    # strategy_insights table
    # ------------------------------------------------------------------

    def save_insight(self, insight: str, products_affected: list[str], confidence: float) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO strategy_insights (insight, products_affected, confidence)
                    VALUES (%s, %s, %s) RETURNING id
                    """,
                    (insight, json.dumps(products_affected), confidence),
                )
                return str(cur.fetchone()["id"])

    def get_recent_insights(self, limit: int = 10) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM strategy_insights ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
                return [dict(r) for r in cur.fetchall()]

    def mark_insight_actioned(self, insight_id: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE strategy_insights SET actioned = TRUE WHERE id = %s", (insight_id,))

    # ------------------------------------------------------------------
    # recommendations table
    # ------------------------------------------------------------------

    def save_recommendation(
        self,
        recommendation: str,
        rationale: str,
        agent_target: str,
        confidence: float,
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO recommendations (recommendation, rationale, agent_target, confidence)
                    VALUES (%s, %s, %s, %s) RETURNING id
                    """,
                    (recommendation, rationale, agent_target, confidence),
                )
                return str(cur.fetchone()["id"])

    def mark_recommendation_executed(self, rec_id: str, outcome: str = "") -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE recommendations SET executed = TRUE, outcome = %s WHERE id = %s",
                    (outcome, rec_id),
                )

    # ------------------------------------------------------------------
    # pivot_alerts table
    # ------------------------------------------------------------------

    def save_pivot_alert(
        self,
        product: str,
        diagnosis: str,
        options: list[dict],
        recommended_option: str,
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO pivot_alerts (product, diagnosis, options, recommended_option)
                    VALUES (%s, %s, %s, %s) RETURNING id
                    """,
                    (product, diagnosis, json.dumps(options), recommended_option),
                )
                return str(cur.fetchone()["id"])

    # ------------------------------------------------------------------
    # metrics queries (used by PivotDetector)
    # ------------------------------------------------------------------

    def get_mrr_trend(self, product: str, weeks: int = 4) -> list[dict[str, Any]]:
        """Return recent MRR data points from strategy_signals (revenue type)."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT created_at::date AS week, summary, recommendation
                    FROM strategy_signals
                    WHERE product = %s AND signal_type IN ('retention', 'market', 'revenue')
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (product, weeks),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_conversion_rate(self, product: str, days: int = 30) -> float:
        """Return the most recently recorded conversion rate for a product from signals."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT recommendation FROM strategy_signals
                    WHERE product = %s AND signal_type = 'conversion'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (product,),
                )
                row = cur.fetchone()
        if row:
            try:
                return float(row["recommendation"])
            except (ValueError, TypeError):
                pass
        return 0.0
