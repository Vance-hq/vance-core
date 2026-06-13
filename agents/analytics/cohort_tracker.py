"""CohortTracker — monthly cohort retention at 30/60/90 days."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import AnalyticsDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are a SaaS retention analyst. Given monthly cohort data, identify which cohorts "
    "retain better and why. Correlate with available signals (acquisition channel, onboarding "
    "completion). Output JSON only: "
    "{\"insights\": [str], \"best_cohort\": str, \"worst_cohort\": str, \"recommendation\": str}"
)


def _enqueue_strategy(product: str, insights: list[str], recommendation: str) -> None:
    try:
        TaskQueue().push(
            agent="strategy",
            payload={
                "action": "retention_signal",
                "product": product,
                "insights": insights,
                "recommendation": recommendation,
                "source": "analytics",
            },
        )
    except Exception as exc:
        logger.warning("enqueue_strategy_failed", error=str(exc))


class CohortTracker:

    def __init__(self, db: AnalyticsDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str, cohort_month: str | None = None) -> dict[str, Any]:
        from datetime import date
        month = cohort_month or date.today().strftime("%Y-%m")

        cohort_size, d30, d60, d90 = self._calculate_retention(product, month)
        self._db.upsert_cohort(
            product=product,
            cohort_month=month,
            cohort_size=cohort_size,
            day_30=d30,
            day_60=d60,
            day_90=d90,
        )

        all_cohorts = self._db.list_cohorts(product=product, limit=12)
        analysis = self._analyze_cohorts(product, all_cohorts)

        if analysis.get("insights"):
            _enqueue_strategy(
                product=product,
                insights=analysis["insights"],
                recommendation=analysis.get("recommendation", ""),
            )

        logger.info("cohort_tracked", product=product, month=month, cohort_size=cohort_size)
        return {
            "product": product,
            "cohort_month": month,
            "cohort_size": cohort_size,
            "day_30_retention": d30,
            "day_60_retention": d60,
            "day_90_retention": d90,
            "analysis": analysis,
        }

    def _calculate_retention(
        self,
        product: str,
        cohort_month: str,
    ) -> tuple[int, float | None, float | None, float | None]:
        """Query usage snapshots to derive retention for cohort month."""
        try:
            from shared.db.client import get_db
            with get_db() as conn:
                with conn.cursor() as cur:
                    # Cohort size = distinct users who signed up in the month
                    cur.execute(
                        """
                        SELECT COUNT(DISTINCT user_id)::int as cohort_size,
                               COUNT(DISTINCT CASE WHEN days_since_signup >= 30
                                    AND last_active >= signup_date + 30 THEN user_id END)::int as d30,
                               COUNT(DISTINCT CASE WHEN days_since_signup >= 60
                                    AND last_active >= signup_date + 60 THEN user_id END)::int as d60,
                               COUNT(DISTINCT CASE WHEN days_since_signup >= 90
                                    AND last_active >= signup_date + 90 THEN user_id END)::int as d90
                        FROM (
                            SELECT user_id,
                                   MIN(created_at)::date AS signup_date,
                                   MAX(last_active_at)::date AS last_active,
                                   (CURRENT_DATE - MIN(created_at)::date) AS days_since_signup
                            FROM user_activity
                            WHERE product = %s
                              AND TO_CHAR(created_at, 'YYYY-MM') = %s
                            GROUP BY user_id
                        ) sub
                        """,
                        (product, cohort_month),
                    )
                    row = cur.fetchone()
                    size = row[0] or 0
                    d30_count, d60_count, d90_count = row[1] or 0, row[2] or 0, row[3] or 0
        except Exception as exc:
            logger.warning("cohort_db_query_failed", error=str(exc))
            return 0, None, None, None

        d30 = round(d30_count / size, 4) if size > 0 else None
        d60 = round(d60_count / size, 4) if size > 0 else None
        d90 = round(d90_count / size, 4) if size > 0 else None
        return size, d30, d60, d90

    def _analyze_cohorts(self, product: str, cohorts: list[dict[str, Any]]) -> dict[str, Any]:
        if not cohorts:
            return {"insights": [], "recommendation": "No cohort data available yet."}

        summary = json.dumps(
            [{"month": c["cohort_month"], "size": c["cohort_size"],
              "d30": float(c["day_30_retention"]) if c.get("day_30_retention") else None,
              "d60": float(c["day_60_retention"]) if c.get("day_60_retention") else None,
              "d90": float(c["day_90_retention"]) if c.get("day_90_retention") else None}
             for c in cohorts],
            indent=2,
        )

        resp = llm.complete(
            messages=[{"role": "user", "content": f"Product: {product}\nCohort data:\n{summary}"}],
            system=_SYSTEM,
            max_tokens=512,
        )
        raw = resp.content[0].text.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"insights": [raw[:300]], "recommendation": ""}
