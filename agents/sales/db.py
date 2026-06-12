"""DB helpers for the sales agent."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class SalesDB:

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def get_user_by_stripe_customer(self, stripe_customer_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE stripe_customer_id = %s LIMIT 1", (stripe_customer_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def stalled_trials(self, stall_days: int, inactivity_hours: int) -> list[dict[str, Any]]:
        """Users in trial who haven't logged in and haven't converted."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM users
                    WHERE plan = 'trial'
                      AND converted_at IS NULL
                      AND churned_at IS NULL
                      AND trial_started_at < now() - (%s || ' days')::INTERVAL
                      AND (last_login_at IS NULL
                           OR last_login_at < now() - (%s || ' hours')::INTERVAL)
                    ORDER BY trial_started_at ASC
                    LIMIT 500
                    """,
                    (stall_days, inactivity_hours),
                )
                return [dict(r) for r in cur.fetchall()]

    def upgrade_candidates(self, plans: list[str]) -> list[dict[str, Any]]:
        """Active users on given plans who have hit feature gates."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT u.*, COUNT(f.id) AS blocked_attempts,
                           MAX(f.feature) AS last_blocked_feature,
                           MAX(f.attempted_at) AS last_blocked_at
                    FROM users u
                    JOIN user_feature_attempts f ON f.user_id = u.id AND f.blocked_by_plan = TRUE
                    WHERE u.plan = ANY(%s)
                      AND u.converted_at IS NOT NULL
                      AND u.churned_at IS NULL
                      AND f.attempted_at > now() - INTERVAL '14 days'
                    GROUP BY u.id
                    HAVING COUNT(f.id) >= 1
                    ORDER BY COUNT(f.id) DESC, u.engagement_score DESC
                    LIMIT 200
                    """,
                    (plans,),
                )
                return [dict(r) for r in cur.fetchall()]

    def churned_in_window(self, min_days: int, max_days: int) -> list[dict[str, Any]]:
        """Churned users within a recency window — for win-back."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM users
                    WHERE churned_at IS NOT NULL
                      AND churned_at BETWEEN now() - (%s || ' days')::INTERVAL
                                        AND now() - (%s || ' days')::INTERVAL
                    ORDER BY churned_at DESC
                    LIMIT 200
                    """,
                    (max_days, min_days),
                )
                return [dict(r) for r in cur.fetchall()]

    def referral_candidates(self, nps_threshold: int, active_days: int) -> list[dict[str, Any]]:
        """Happy long-term users who haven't yet received a referral invite."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT u.* FROM users u
                    WHERE u.nps_score >= %s
                      AND u.created_at < now() - (%s || ' days')::INTERVAL
                      AND u.churned_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM sales_actions sa
                          WHERE sa.user_id = u.id
                            AND sa.action_type = 'referral_invite'
                      )
                    ORDER BY u.nps_score DESC, u.engagement_score DESC
                    LIMIT 100
                    """,
                    (nps_threshold, active_days),
                )
                return [dict(r) for r in cur.fetchall()]

    def user_usage_summary(self, user_id: str) -> dict[str, Any]:
        """Pull usage signals for churn recovery personalisation."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        u.product,
                        u.plan,
                        u.email,
                        u.company,
                        u.engagement_score,
                        EXTRACT(DAY FROM (COALESCE(u.churned_at, now()) - u.created_at))::INT AS days_active,
                        COUNT(DISTINCT f.feature) AS features_used,
                        SUM(CASE WHEN f.blocked_by_plan THEN 1 ELSE 0 END) AS blocked_attempts
                    FROM users u
                    LEFT JOIN user_feature_attempts f ON f.user_id = u.id
                    WHERE u.id = %s
                    GROUP BY u.id
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else {}

    # ------------------------------------------------------------------
    # Sales actions
    # ------------------------------------------------------------------

    def log_action(
        self,
        product: str,
        action_type: str,
        user_id: str | None = None,
        contact_id: str | None = None,
        outcome: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO sales_actions (id, user_id, contact_id, product, action_type, outcome, meta)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row_id,
                        user_id,
                        contact_id,
                        product,
                        action_type,
                        outcome,
                        psycopg2.extras.Json(meta or {}),
                    ),
                )
                conn.commit()
                return row_id

    def update_action_outcome(self, action_id: str, outcome: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sales_actions SET outcome = %s WHERE id = %s",
                    (outcome, action_id),
                )
                conn.commit()

    def days_since_last_action(self, user_id: str, action_type: str) -> float:
        """Returns days since the last action of given type for this user. inf if never."""
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXTRACT(EPOCH FROM (now() - sent_at)) / 86400
                    FROM sales_actions
                    WHERE user_id = %s AND action_type = %s
                    ORDER BY sent_at DESC LIMIT 1
                    """,
                    (user_id, action_type),
                )
                row = cur.fetchone()
                return float(row[0]) if row else float("inf")

    # ------------------------------------------------------------------
    # Churn recovery
    # ------------------------------------------------------------------

    def log_churn_recovery(
        self,
        user_id: str,
        product: str,
        extension_applied: bool = False,
        stripe_coupon_id: str | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO churn_recovery_attempts
                        (id, user_id, product, extension_applied, stripe_coupon_id)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (row_id, user_id, product, extension_applied, stripe_coupon_id),
                )
                conn.commit()
                return row_id

    def update_churn_outcome(self, attempt_id: str, outcome: str, days_to_respond: int | None = None) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE churn_recovery_attempts
                    SET outcome = %s, days_to_respond = %s
                    WHERE id = %s
                    """,
                    (outcome, days_to_respond, attempt_id),
                )
                conn.commit()

    def win_back_sent_within(self, user_id: str, days: int) -> bool:
        """True if a win_back action was sent to this user within the last N days."""
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM sales_actions
                    WHERE user_id = %s
                      AND action_type = 'win_back'
                      AND sent_at > now() - (%s || ' days')::INTERVAL
                    LIMIT 1
                    """,
                    (user_id, days),
                )
                return cur.fetchone() is not None
