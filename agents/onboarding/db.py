"""
Onboarding DB — onboarding_state, activation_events tables.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class OnboardingDB:

    # ------------------------------------------------------------------
    # onboarding_state
    # ------------------------------------------------------------------

    def upsert_state(
        self,
        user_id: str,
        product: str,
        current_milestone: str,
        milestones_completed: list[str] | None = None,
        last_nudge_at: datetime | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO onboarding_state
                        (user_id, product, current_milestone, milestones_completed, last_nudge_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, product) DO UPDATE SET
                        current_milestone = EXCLUDED.current_milestone,
                        milestones_completed = EXCLUDED.milestones_completed,
                        last_nudge_at = COALESCE(EXCLUDED.last_nudge_at, onboarding_state.last_nudge_at)
                    RETURNING id
                    """,
                    (
                        user_id,
                        product,
                        current_milestone,
                        json.dumps(milestones_completed or []),
                        last_nudge_at,
                    ),
                )
                row = cur.fetchone()
        return str(row["id"])

    def get_state(
        self,
        user_id: str,
        product: str,
    ) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM onboarding_state WHERE user_id = %s AND product = %s",
                    (user_id, product),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_stuck_users(self, days_inactive: int = 5) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM onboarding_state
                    WHERE created_at < NOW() - INTERVAL '%s days'
                      AND milestones_completed = '[]'::jsonb
                    ORDER BY created_at ASC
                    """,
                    (days_inactive,),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # activation_events
    # ------------------------------------------------------------------

    def record_milestone(
        self,
        user_id: str,
        product: str,
        milestone: str,
        days_since_signup: int,
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO activation_events
                        (user_id, product, milestone, days_since_signup)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (user_id, product, milestone, days_since_signup),
                )
                row = cur.fetchone()
        return str(row["id"])

    def list_milestone_times(
        self,
        product: str,
        milestone: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM activation_events
                    WHERE product = %s AND milestone = %s
                    ORDER BY achieved_at DESC
                    LIMIT %s
                    """,
                    (product, milestone, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_funnel_metrics(self, product: str) -> dict[str, Any]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(DISTINCT user_id) FILTER (WHERE milestones_completed != '[]'::jsonb)
                            * 100.0 / NULLIF(COUNT(DISTINCT user_id), 0) AS signup_to_activated_pct,
                        AVG(ae.days_since_signup) AS avg_days_to_first_value
                    FROM onboarding_state os
                    LEFT JOIN activation_events ae
                        ON ae.user_id = os.user_id AND ae.product = os.product
                    WHERE os.product = %s
                    """,
                    (product,),
                )
                row = cur.fetchone() or {}
                return {
                    "signup_to_activated_pct": float(row.get("signup_to_activated_pct") or 0),
                    "avg_days_to_first_value": float(row.get("avg_days_to_first_value") or 0),
                }
