"""Analytics DB — usage_snapshots, funnel_snapshots, cohort_data, feature_usage, engagement_scores, ab_tests."""

from __future__ import annotations

import json
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class AnalyticsDB:

    # ------------------------------------------------------------------
    # usage_snapshots
    # ------------------------------------------------------------------

    def upsert_usage_snapshot(self, product: str, date: str, metrics: dict[str, Any]) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usage_snapshots (product, date, metrics)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (product, date) DO UPDATE SET metrics = EXCLUDED.metrics
                    """,
                    (product, date, json.dumps(metrics)),
                )

    def get_usage_snapshot(self, product: str, date: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM usage_snapshots WHERE product = %s AND date = %s",
                    (product, date),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_recent_usage(self, product: str, days: int = 7) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM usage_snapshots
                    WHERE product = %s AND date >= CURRENT_DATE - %s::int
                    ORDER BY date DESC
                    """,
                    (product, days),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_all_products_today(self) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM usage_snapshots WHERE date = CURRENT_DATE"
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # funnel_snapshots
    # ------------------------------------------------------------------

    def insert_funnel_step(
        self,
        product: str,
        date: str,
        step: str,
        count: int,
        conversion_rate: float | None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO funnel_snapshots (product, date, step, count, conversion_rate_from_prev)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (product, date, step, count, conversion_rate),
                )

    def get_funnel_steps(self, product: str, date: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT step, count, conversion_rate_from_prev
                    FROM funnel_snapshots
                    WHERE product = %s AND date = %s
                    ORDER BY created_at
                    """,
                    (product, date),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_funnel_week_prior(self, product: str, date: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT step, SUM(count)::int as count
                    FROM funnel_snapshots
                    WHERE product = %s
                      AND date >= %s::date - 13
                      AND date <= %s::date - 7
                    GROUP BY step
                    ORDER BY MIN(created_at)
                    """,
                    (product, date, date),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # cohort_data
    # ------------------------------------------------------------------

    def upsert_cohort(
        self,
        product: str,
        cohort_month: str,
        cohort_size: int,
        day_30: float | None,
        day_60: float | None,
        day_90: float | None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cohort_data
                        (product, cohort_month, cohort_size, day_30_retention, day_60_retention, day_90_retention)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (product, cohort_month) DO UPDATE SET
                        cohort_size        = EXCLUDED.cohort_size,
                        day_30_retention   = EXCLUDED.day_30_retention,
                        day_60_retention   = EXCLUDED.day_60_retention,
                        day_90_retention   = EXCLUDED.day_90_retention
                    """,
                    (product, cohort_month, cohort_size, day_30, day_60, day_90),
                )

    def list_cohorts(self, product: str, limit: int = 12) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM cohort_data
                    WHERE product = %s
                    ORDER BY cohort_month DESC LIMIT %s
                    """,
                    (product, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # feature_usage
    # ------------------------------------------------------------------

    def upsert_feature_usage(
        self,
        product: str,
        feature_name: str,
        week: str,
        unique_users: int,
        total_events: int,
        adoption_pct: float | None = None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO feature_usage
                        (product, feature_name, week, unique_users, total_events, adoption_pct)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (product, feature_name, week) DO UPDATE SET
                        unique_users = EXCLUDED.unique_users,
                        total_events = EXCLUDED.total_events,
                        adoption_pct = EXCLUDED.adoption_pct
                    """,
                    (product, feature_name, week, unique_users, total_events, adoption_pct),
                )

    def get_feature_usage(self, product: str, week: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM feature_usage
                    WHERE product = %s AND week = %s
                    ORDER BY unique_users DESC
                    """,
                    (product, week),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # engagement_scores
    # ------------------------------------------------------------------

    def upsert_engagement_score(
        self,
        user_id: str,
        product: str,
        score: float,
        tier: str,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO engagement_scores (user_id, product, score, tier, calculated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id, product) DO UPDATE SET
                        score         = EXCLUDED.score,
                        tier          = EXCLUDED.tier,
                        calculated_at = NOW()
                    """,
                    (user_id, product, score, tier),
                )

    def get_users_by_tier(self, product: str, tier: str, limit: int = 500) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT user_id, score, tier, calculated_at
                    FROM engagement_scores
                    WHERE product = %s AND tier = %s
                    ORDER BY score DESC LIMIT %s
                    """,
                    (product, tier, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_tier_counts(self, product: str) -> dict[str, int]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT tier, COUNT(*)::int as cnt
                    FROM engagement_scores
                    WHERE product = %s
                    GROUP BY tier
                    """,
                    (product,),
                )
                return {r["tier"]: r["cnt"] for r in cur.fetchall()}

    # ------------------------------------------------------------------
    # ab_tests
    # ------------------------------------------------------------------

    def upsert_ab_test(
        self,
        agent: str,
        product: str,
        test_name: str,
        variant_a: str,
        variant_b: str,
        metric: str,
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO ab_tests (agent, product, test_name, variant_a, variant_b, metric)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (agent, product, test_name) DO UPDATE SET updated_at = NOW()
                    RETURNING id
                    """,
                    (agent, product, test_name, variant_a, variant_b, metric),
                )
                row = cur.fetchone()
        return str(row["id"])

    def record_ab_result(
        self,
        agent: str,
        product: str,
        test_name: str,
        sample_a: int,
        sample_b: int,
        conversions_a: int,
        conversions_b: int,
        p_value: float | None,
        winner: str | None,
        status: str,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ab_tests SET
                        sample_size_a = %s,
                        sample_size_b = %s,
                        conversions_a = %s,
                        conversions_b = %s,
                        p_value       = %s,
                        winner        = %s,
                        status        = %s,
                        updated_at    = NOW()
                    WHERE agent = %s AND product = %s AND test_name = %s
                    """,
                    (sample_a, sample_b, conversions_a, conversions_b,
                     p_value, winner, status,
                     agent, product, test_name),
                )

    def get_running_tests(self) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM ab_tests WHERE status = 'running' ORDER BY created_at"
                )
                return [dict(r) for r in cur.fetchall()]

    def get_ab_test(self, agent: str, product: str, test_name: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM ab_tests WHERE agent = %s AND product = %s AND test_name = %s",
                    (agent, product, test_name),
                )
                row = cur.fetchone()
        return dict(row) if row else None
