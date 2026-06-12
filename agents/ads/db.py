"""DB helpers for the ads agent."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class AdsDB:

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------

    def create_campaign(
        self,
        product: str,
        platform: str,
        name: str,
        objective: str,
        budget_daily: float,
        platform_campaign_id: str | None = None,
        platform_ad_set_id: str | None = None,
        platform_budget_resource: str | None = None,
        target_cpa: float | None = None,
        target_roas: float | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO ad_campaigns
                        (id, product, platform, name, objective, budget_daily,
                         platform_campaign_id, platform_ad_set_id, platform_budget_resource,
                         target_cpa, target_roas)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        row_id, product, platform, name, objective, budget_daily,
                        platform_campaign_id, platform_ad_set_id, platform_budget_resource,
                        target_cpa, target_roas,
                    ),
                )
                conn.commit()
                return row_id

    def update_campaign_platform_ids(
        self,
        campaign_id: str,
        platform_campaign_id: str | None = None,
        platform_ad_set_id: str | None = None,
        platform_budget_resource: str | None = None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ad_campaigns
                    SET platform_campaign_id   = COALESCE(%s, platform_campaign_id),
                        platform_ad_set_id     = COALESCE(%s, platform_ad_set_id),
                        platform_budget_resource = COALESCE(%s, platform_budget_resource)
                    WHERE id = %s
                    """,
                    (platform_campaign_id, platform_ad_set_id, platform_budget_resource, campaign_id),
                )
                conn.commit()

    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM ad_campaigns WHERE id = %s", (campaign_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def get_active_campaigns(self, platform: str | None = None) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if platform:
                    cur.execute(
                        "SELECT * FROM ad_campaigns WHERE status = 'active' AND platform = %s",
                        (platform,),
                    )
                else:
                    cur.execute("SELECT * FROM ad_campaigns WHERE status = 'active'")
                return [dict(r) for r in cur.fetchall()]

    def update_campaign_status(self, campaign_id: str, status: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                paused_at = "now()" if status == "paused" else "NULL"
                cur.execute(
                    f"UPDATE ad_campaigns SET status = %s, paused_at = {paused_at} WHERE id = %s",
                    (status, campaign_id),
                )
                conn.commit()

    def update_campaign_budget(self, campaign_id: str, new_budget: float) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ad_campaigns SET budget_daily = %s WHERE id = %s",
                    (new_budget, campaign_id),
                )
                conn.commit()

    # ------------------------------------------------------------------
    # Performance
    # ------------------------------------------------------------------

    def log_performance(
        self,
        campaign_id: str,
        perf_date: date,
        spend: float,
        impressions: int,
        clicks: int,
        conversions: float,
        cpa: float | None,
        roas: float | None,
        ctr: float | None,
        frequency: float | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO ad_performance
                        (id, campaign_id, date, spend, impressions, clicks,
                         conversions, cpa, roas, ctr, frequency)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (campaign_id, date) DO UPDATE
                        SET spend       = EXCLUDED.spend,
                            impressions = EXCLUDED.impressions,
                            clicks      = EXCLUDED.clicks,
                            conversions = EXCLUDED.conversions,
                            cpa         = EXCLUDED.cpa,
                            roas        = EXCLUDED.roas,
                            ctr         = EXCLUDED.ctr,
                            frequency   = EXCLUDED.frequency
                    """,
                    (
                        row_id, campaign_id, perf_date, spend, impressions,
                        clicks, conversions, cpa, roas, ctr, frequency,
                    ),
                )
                conn.commit()
                return row_id

    def get_recent_performance(
        self, campaign_id: str, days: int = 7
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM ad_performance
                    WHERE campaign_id = %s AND date > now()::DATE - %s
                    ORDER BY date DESC
                    """,
                    (campaign_id, days),
                )
                return [dict(r) for r in cur.fetchall()]

    def consecutive_cpa_breaches(
        self, campaign_id: str, target_cpa: float, multiplier: float = 1.5
    ) -> int:
        """Count consecutive most-recent days where CPA > target * multiplier."""
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cpa FROM ad_performance
                    WHERE campaign_id = %s AND cpa IS NOT NULL
                    ORDER BY date DESC LIMIT 7
                    """,
                    (campaign_id,),
                )
                rows = cur.fetchall()
                threshold = target_cpa * multiplier
                consecutive = 0
                for (cpa_val,) in rows:
                    if float(cpa_val) > threshold:
                        consecutive += 1
                    else:
                        break
                return consecutive

    def all_campaigns_roas(self, days: int = 7) -> list[dict[str, Any]]:
        """Return campaign_id, avg ROAS, current budget for active campaigns."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT c.id, c.budget_daily, c.platform, c.platform_campaign_id,
                           c.platform_budget_resource, c.product,
                           AVG(p.roas) AS avg_roas
                    FROM ad_campaigns c
                    LEFT JOIN ad_performance p
                      ON p.campaign_id = c.id AND p.date > now()::DATE - %s
                    WHERE c.status = 'active'
                    GROUP BY c.id
                    ORDER BY avg_roas DESC NULLS LAST
                    """,
                    (days,),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Creative tests
    # ------------------------------------------------------------------

    def create_creative_test(
        self,
        campaign_id: str,
        variant_a: str,
        variant_b: str,
        variant_a_platform_id: str | None = None,
        variant_b_platform_id: str | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO creative_tests
                        (id, campaign_id, variant_a, variant_b,
                         variant_a_platform_id, variant_b_platform_id)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    """,
                    (row_id, campaign_id, variant_a, variant_b,
                     variant_a_platform_id, variant_b_platform_id),
                )
                conn.commit()
                return row_id

    def get_running_tests(self, campaign_id: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM creative_tests WHERE campaign_id = %s AND status = 'running'",
                    (campaign_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    def update_test_impressions(
        self,
        test_id: str,
        impressions_a: int,
        impressions_b: int,
        clicks_a: int,
        clicks_b: int,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE creative_tests
                    SET impressions_a = %s, impressions_b = %s,
                        clicks_a = %s, clicks_b = %s
                    WHERE id = %s
                    """,
                    (impressions_a, impressions_b, clicks_a, clicks_b, test_id),
                )
                conn.commit()

    def resolve_test(self, test_id: str, winner: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE creative_tests SET winner = %s, status = 'complete' WHERE id = %s",
                    (winner, test_id),
                )
                conn.commit()

    # ------------------------------------------------------------------
    # Budget log
    # ------------------------------------------------------------------

    def log_budget_change(
        self,
        campaign_id: str,
        old_budget: float,
        new_budget: float,
        reason: str,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO ad_budget_log (id, campaign_id, old_budget, new_budget, reason)
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    (row_id, campaign_id, old_budget, new_budget, reason),
                )
                conn.commit()
                return row_id

    # ------------------------------------------------------------------
    # Customer emails (for audience targeting)
    # ------------------------------------------------------------------

    def get_converted_emails(self, product: str, limit: int = 2000) -> list[str]:
        """Return emails of converted (paying) users for a product."""
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT email FROM users
                    WHERE product = %s
                      AND converted_at IS NOT NULL
                      AND churned_at IS NULL
                    LIMIT %s
                    """,
                    (product, limit),
                )
                return [row[0] for row in cur.fetchall()]
