"""FunnelAnalyzer — visit → signup → activated → paid → retained conversion funnel."""

from __future__ import annotations

from datetime import date
from typing import Any

from shared.logger import get_logger

from .db import AnalyticsDB

logger = get_logger(__name__)

FUNNEL_STEPS = ["visit", "signup", "activated", "paid", "retained"]
REGRESSION_THRESHOLD = 0.15


class FunnelAnalyzer:

    def __init__(self, db: AnalyticsDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str, date_str: str | None = None) -> dict[str, Any]:
        today = date_str or date.today().isoformat()
        counts = self._collect_counts(product, today)
        steps = self._build_steps(counts)

        for s in steps:
            self._db.insert_funnel_step(
                product=product,
                date=today,
                step=s["step"],
                count=s["count"],
                conversion_rate=s["conversion_rate"],
            )

        # week-over-week regression check
        regressions = self._check_regressions(product, today, steps)

        logger.info("funnel_analysis_complete", product=product, date=today, regressions=len(regressions))
        return {
            "product": product,
            "date": today,
            "steps": steps,
            "regressions": regressions,
        }

    def _collect_counts(self, product: str, date_str: str) -> dict[str, int]:
        """Pull step counts from usage_snapshots and DB views."""
        recent = self._db.get_recent_usage(product=product, days=1)
        metrics = recent[0]["metrics"] if recent else {}

        prod_cfg = self._cfg.get("products", {}).get(product, {})
        mapping = prod_cfg.get("funnel_metric_map", {})

        return {
            "visit":     int(metrics.get(mapping.get("visit", "site_visits"), 0)),
            "signup":    int(metrics.get(mapping.get("signup", "signups"), 0)),
            "activated": int(metrics.get(mapping.get("activated", "activated_users"), 0)),
            "paid":      int(metrics.get(mapping.get("paid", "paid_users"), 0)),
            "retained":  int(metrics.get(mapping.get("retained", "retained_users"), 0)),
        }

    def _build_steps(self, counts: dict[str, int]) -> list[dict[str, Any]]:
        steps = []
        prev_count: int | None = None
        for step in FUNNEL_STEPS:
            count = counts.get(step, 0)
            conversion = None
            if prev_count and prev_count > 0:
                conversion = round(count / prev_count, 4)
            steps.append({"step": step, "count": count, "conversion_rate": conversion})
            prev_count = count
        return steps

    def _check_regressions(
        self,
        product: str,
        today: str,
        current_steps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        prior_rows = self._db.get_funnel_week_prior(product=product, date=today)
        if not prior_rows:
            return []

        prior_counts = {r["step"]: r["count"] for r in prior_rows}
        prior_steps = self._build_steps(
            {s: prior_counts.get(s, 0) for s in FUNNEL_STEPS}
        )
        prior_conv = {s["step"]: s["conversion_rate"] for s in prior_steps}

        regressions = []
        for s in current_steps:
            prev = prior_conv.get(s["step"])
            curr = s["conversion_rate"]
            if prev and curr is not None and prev > 0:
                drop = (prev - curr) / prev
                if drop >= REGRESSION_THRESHOLD:
                    regressions.append({
                        "step": s["step"],
                        "prior_conversion": prev,
                        "current_conversion": curr,
                        "drop_pct": round(drop, 4),
                    })
        return regressions
