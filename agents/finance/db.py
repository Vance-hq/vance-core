"""Postgres helpers for the finance agent."""

from __future__ import annotations

from datetime import date, datetime, timezone

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class FinanceDB:
    # ------------------------------------------------------------------
    # MRR snapshots
    # ------------------------------------------------------------------

    def upsert_mrr_snapshot(
        self,
        *,
        snapshot_date: date,
        product: str,
        mrr_cents: int,
        arr_cents: int,
        subscriber_count: int,
        new_mrr_cents: int = 0,
        churned_mrr_cents: int = 0,
        metadata: dict | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mrr_snapshots
                        (snapshot_date, product, mrr_cents, arr_cents, subscriber_count,
                         new_mrr_cents, churned_mrr_cents, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (snapshot_date, product) DO UPDATE SET
                        mrr_cents        = EXCLUDED.mrr_cents,
                        arr_cents        = EXCLUDED.arr_cents,
                        subscriber_count = EXCLUDED.subscriber_count,
                        new_mrr_cents    = EXCLUDED.new_mrr_cents,
                        churned_mrr_cents = EXCLUDED.churned_mrr_cents,
                        metadata         = EXCLUDED.metadata
                    RETURNING id
                    """,
                    (
                        snapshot_date,
                        product,
                        mrr_cents,
                        arr_cents,
                        subscriber_count,
                        new_mrr_cents,
                        churned_mrr_cents,
                        psycopg2.extras.Json(metadata or {}),
                    ),
                )
                return str(cur.fetchone()[0])

    def get_mrr_history(self, product: str = "default", days: int = 30) -> list[dict]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM mrr_snapshots
                    WHERE product = %s
                      AND snapshot_date >= CURRENT_DATE - INTERVAL '%s days'
                    ORDER BY snapshot_date DESC
                    """,
                    (product, days),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_latest_mrr(self, product: str = "default") -> dict | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM mrr_snapshots
                    WHERE product = %s
                    ORDER BY snapshot_date DESC
                    LIMIT 1
                    """,
                    (product,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_previous_mrr(self, product: str = "default", before_date: date | None = None) -> dict | None:
        """Return the snapshot immediately before before_date (default: yesterday)."""
        if before_date is None:
            before_date = date.today()
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM mrr_snapshots
                    WHERE product = %s AND snapshot_date < %s
                    ORDER BY snapshot_date DESC
                    LIMIT 1
                    """,
                    (product, before_date),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    # ------------------------------------------------------------------
    # Cost snapshots
    # ------------------------------------------------------------------

    def upsert_cost_snapshot(
        self,
        *,
        period_month: date,
        vendor: str,
        cost_cents: int,
        category: str = "infrastructure",
        metadata: dict | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cost_snapshots
                        (period_month, vendor, cost_cents, category, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (period_month, vendor) DO UPDATE SET
                        cost_cents = EXCLUDED.cost_cents,
                        category   = EXCLUDED.category,
                        metadata   = EXCLUDED.metadata
                    RETURNING id
                    """,
                    (
                        period_month,
                        vendor,
                        cost_cents,
                        category,
                        psycopg2.extras.Json(metadata or {}),
                    ),
                )
                return str(cur.fetchone()[0])

    def get_cost_history(self, months: int = 3) -> list[dict]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM cost_snapshots
                    WHERE period_month >= DATE_TRUNC('month', NOW() - INTERVAL '%s months')
                    ORDER BY period_month DESC, vendor
                    """,
                    (months,),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_total_cost_for_month(self, period_month: date) -> int:
        """Return sum of all vendor costs for the given month in cents."""
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(SUM(cost_cents), 0) FROM cost_snapshots WHERE period_month = %s",
                    (period_month,),
                )
                return int(cur.fetchone()[0])

    # ------------------------------------------------------------------
    # Unit economics
    # ------------------------------------------------------------------

    def upsert_unit_economics(
        self,
        *,
        period_month: date,
        cac_cents: int,
        ltv_cents: int,
        ltv_cac_ratio: float,
        payback_months: float,
        new_customers: int,
        sales_marketing_spend_cents: int,
        metadata: dict | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO unit_economics
                        (period_month, cac_cents, ltv_cents, ltv_cac_ratio, payback_months,
                         new_customers, sales_marketing_spend_cents, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (period_month) DO UPDATE SET
                        cac_cents                   = EXCLUDED.cac_cents,
                        ltv_cents                   = EXCLUDED.ltv_cents,
                        ltv_cac_ratio               = EXCLUDED.ltv_cac_ratio,
                        payback_months              = EXCLUDED.payback_months,
                        new_customers               = EXCLUDED.new_customers,
                        sales_marketing_spend_cents = EXCLUDED.sales_marketing_spend_cents,
                        metadata                    = EXCLUDED.metadata
                    RETURNING id
                    """,
                    (
                        period_month,
                        cac_cents,
                        ltv_cents,
                        ltv_cac_ratio,
                        payback_months,
                        new_customers,
                        sales_marketing_spend_cents,
                        psycopg2.extras.Json(metadata or {}),
                    ),
                )
                return str(cur.fetchone()[0])

    def get_latest_unit_economics(self) -> dict | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM unit_economics ORDER BY period_month DESC LIMIT 1"
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_unit_economics_history(self, months: int = 6) -> list[dict]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM unit_economics
                    WHERE period_month >= DATE_TRUNC('month', NOW() - INTERVAL '%s months')
                    ORDER BY period_month DESC
                    """,
                    (months,),
                )
                return [dict(r) for r in cur.fetchall()]
