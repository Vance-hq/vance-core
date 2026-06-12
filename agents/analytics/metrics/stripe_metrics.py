"""Stripe revenue metrics — MRR, ARR, churn, cohorts."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from agents.integrations.connectors.stripe import StripeConnector
from shared.logger import get_logger

logger = get_logger(__name__)


class StripeMetrics:
    def __init__(self, task_id: str | None = None) -> None:
        self._stripe = StripeConnector(
            task_id=task_id,
            called_by="analytics",
            method_name="stripe_metrics",
        )

    def snapshot(self) -> dict[str, Any]:
        """Pull all revenue metrics in one pass. Returns flat dict keyed by metric name."""
        mrr_data = self._stripe.get_mrr()
        active_subs = mrr_data.get("subscription_count", 0)
        mrr_cents = mrr_data.get("mrr_cents", 0)
        mrr = mrr_cents / 100.0
        arr = mrr * 12.0
        arpu = mrr / active_subs if active_subs else 0.0

        # New MRR this month
        month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        new_subs = self._stripe.list_subscriptions(status="active", limit=100)
        new_mrr = sum(
            (s.get("items", {}).get("data", [{}])[0].get("plan", {}).get("amount", 0) or 0) / 100.0
            for s in new_subs
            if s.get("created", 0) >= int(month_start.timestamp())
        )

        # Churned MRR this month
        canceled_subs = self._stripe.list_subscriptions(status="canceled", limit=100)
        churned_mrr = sum(
            (s.get("items", {}).get("data", [{}])[0].get("plan", {}).get("amount", 0) or 0) / 100.0
            for s in canceled_subs
            if s.get("canceled_at") and s["canceled_at"] >= int(month_start.timestamp())
        )

        churn_rate = (churned_mrr / mrr) if mrr > 0 else 0.0
        ltv = (arpu / churn_rate) if churn_rate > 0 else 0.0

        return {
            "mrr": mrr,
            "arr": arr,
            "new_mrr": new_mrr,
            "churned_mrr": churned_mrr,
            "net_mrr_change": new_mrr - churned_mrr,
            "subscription_count": active_subs,
            "arpu": arpu,
            "churn_rate": churn_rate,
            "ltv_estimate": ltv,
        }

    def monthly_cohorts(self, months: int = 6) -> list[dict]:
        """New subscriptions grouped by calendar month."""
        subs = self._stripe.list_subscriptions(status="active", limit=100)
        cohorts: dict[str, dict] = {}
        for s in subs:
            created = s.get("created")
            if not created:
                continue
            dt = datetime.fromtimestamp(created, tz=timezone.utc)
            key = dt.strftime("%Y-%m")
            amount = (s.get("items", {}).get("data", [{}])[0].get("plan", {}).get("amount", 0) or 0) / 100.0
            if key not in cohorts:
                cohorts[key] = {"month": key, "new_subscriptions": 0, "new_mrr": 0.0}
            cohorts[key]["new_subscriptions"] += 1
            cohorts[key]["new_mrr"] += amount
        return sorted(cohorts.values(), key=lambda c: c["month"], reverse=True)[:months]
