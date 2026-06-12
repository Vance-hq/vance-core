"""MRR snapshot logic — pulls per-product MRR from Stripe and stores it."""

from __future__ import annotations

from datetime import date

from agents.integrations.connectors.stripe import StripeConnector
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import FinanceDB

logger = get_logger(__name__)

MRR_DROP_DEFAULT_THRESHOLD = 0.05  # 5%


class MRRTracker:
    def __init__(self, config: dict, db: FinanceDB | None = None) -> None:
        self._cfg = config
        self._db = db or FinanceDB()
        self._stripe = StripeConnector()
        self._threshold = float(config.get("mrr_drop_alert_threshold", MRR_DROP_DEFAULT_THRESHOLD))
        self._products: dict[str, str] = config.get("products", {"default": ""})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Capture today's MRR for every configured product. Return summary."""
        today = date.today()
        results = {}
        alerts = []

        for product_name, product_id in self._products.items():
            data = self._fetch_stripe_mrr(product_id or None)
            mrr_cents = data["mrr_cents"]
            subscriber_count = data["subscription_count"]
            arr_cents = mrr_cents * 12

            self._db.upsert_mrr_snapshot(
                snapshot_date=today,
                product=product_name,
                mrr_cents=mrr_cents,
                arr_cents=arr_cents,
                subscriber_count=subscriber_count,
                metadata={"product_id": product_id},
            )

            alert = self._check_drop(product_name, mrr_cents)
            if alert:
                alerts.append(alert)

            results[product_name] = {
                "mrr_cents": mrr_cents,
                "arr_cents": arr_cents,
                "subscriber_count": subscriber_count,
            }

        if alerts:
            self._notify_alerts(alerts)

        return {"date": str(today), "products": results, "alerts": alerts}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_stripe_mrr(self, product_id: str | None) -> dict:
        if product_id:
            subs = self._stripe.list_subscriptions(product=product_id, status="active")
            mrr_cents = sum(
                (s.get("items", {}).get("data", [{}])[0].get("plan", {}).get("amount", 0) or 0)
                for s in subs
            )
            return {"mrr_cents": mrr_cents, "subscription_count": len(subs)}
        return self._stripe.get_mrr()

    def _check_drop(self, product: str, current_mrr: int) -> dict | None:
        previous = self._db.get_previous_mrr(product=product)
        if not previous:
            return None
        prev_mrr = previous["mrr_cents"]
        if prev_mrr == 0:
            return None
        drop_pct = (prev_mrr - current_mrr) / prev_mrr
        if drop_pct >= self._threshold:
            return {
                "product": product,
                "drop_pct": round(drop_pct * 100, 2),
                "previous_mrr_cents": prev_mrr,
                "current_mrr_cents": current_mrr,
            }
        return None

    def _notify_alerts(self, alerts: list[dict]) -> None:
        for alert in alerts:
            logger.warning(
                "mrr_drop_alert",
                product=alert["product"],
                drop_pct=alert["drop_pct"],
            )
        TaskQueue().push(
            agent="reporting",
            payload={"action": "mrr_drop_alert", "alerts": alerts},
            priority=2,
        )
