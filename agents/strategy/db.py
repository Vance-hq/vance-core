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
