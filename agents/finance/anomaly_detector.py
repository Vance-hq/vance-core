"""Stripe webhook-triggered anomaly detection for charges, refunds, and payments."""

from __future__ import annotations

from agents.integrations.connectors.stripe import StripeConnector
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

logger = get_logger(__name__)


class AnomalyDetector:
    """Detect unexpected spikes in Stripe events and alert reporting + sales."""

    def __init__(self, config: dict) -> None:
        self._cfg = config
        self._stripe = StripeConnector()
        self._charge_spike_multiplier = float(config.get("charge_spike_multiplier", 3.0))
        self._refund_spike_count = int(config.get("refund_spike_count", 5))
        self._failed_payment_spike_count = int(config.get("failed_payment_spike_count", 10))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, event: dict) -> dict:
        """
        Process a Stripe webhook event dict and return an anomaly report.
        event: {"type": str, "data": {"object": {...}}, ...}
        """
        event_type = event.get("type", "")
        obj = event.get("data", {}).get("object", {})
        anomalies = []

        if event_type == "charge.succeeded":
            anomaly = self._check_charge_spike(obj)
            if anomaly:
                anomalies.append(anomaly)

        elif event_type in ("charge.refunded", "refund.created"):
            anomaly = self._check_refund_spike(obj)
            if anomaly:
                anomalies.append(anomaly)

        elif event_type == "customer.subscription.deleted":
            anomaly = self._check_downgrade_wave(obj)
            if anomaly:
                anomalies.append(anomaly)

        elif event_type == "invoice.payment_failed":
            anomaly = self._check_failed_payment_spike(obj)
            if anomaly:
                anomalies.append(anomaly)

        if anomalies:
            self._notify(anomalies)

        return {"event_type": event_type, "anomalies": anomalies}

    # ------------------------------------------------------------------
    # Spike checks
    # ------------------------------------------------------------------

    def _check_charge_spike(self, obj: dict) -> dict | None:
        amount = obj.get("amount", 0)
        # Compare to recent 30-day average charge amount
        recent = self._stripe.get_revenue_report(
            start_date=self._days_ago(30),
            end_date=self._days_ago(0),
        )
        txn_count = recent.get("transaction_count", 0)
        if txn_count == 0:
            return None
        avg = recent.get("net_cents", 0) / txn_count
        if avg > 0 and amount > avg * self._charge_spike_multiplier:
            return {
                "type": "charge_spike",
                "amount_cents": amount,
                "avg_cents": int(avg),
                "multiplier": round(amount / avg, 2),
            }
        return None

    def _check_refund_spike(self, obj: dict) -> dict | None:
        # Count refunds in last 24h
        refunds = self._stripe.list_invoices(status="void", limit=50)
        recent_count = len([
            r for r in refunds
            if r.get("created", 0) >= self._days_ago(1)
        ])
        if recent_count >= self._refund_spike_count:
            return {
                "type": "refund_spike",
                "count_24h": recent_count,
                "threshold": self._refund_spike_count,
            }
        return None

    def _check_downgrade_wave(self, obj: dict) -> dict | None:
        # Check recent cancellations count via active subscription delta
        data = self._stripe.get_mrr()
        sub_count = data.get("subscription_count", 0)
        # Treat any single cancellation event as worth logging — caller decides severity
        return {
            "type": "subscription_cancelled",
            "current_subscriber_count": sub_count,
            "cancelled_subscription_id": obj.get("id", ""),
        }

    def _check_failed_payment_spike(self, obj: dict) -> dict | None:
        invoices = self._stripe.list_invoices(status="open", limit=100)
        past_due = [
            i for i in invoices
            if i.get("created", 0) >= self._days_ago(1) and i.get("attempt_count", 0) > 0
        ]
        if len(past_due) >= self._failed_payment_spike_count:
            return {
                "type": "failed_payment_spike",
                "count_24h": len(past_due),
                "threshold": self._failed_payment_spike_count,
            }
        return None

    # ------------------------------------------------------------------
    # Notify
    # ------------------------------------------------------------------

    def _notify(self, anomalies: list[dict]) -> None:
        for anomaly in anomalies:
            logger.warning("finance_anomaly", **anomaly)
        TaskQueue().push(
            agent="reporting",
            payload={"action": "finance_anomaly_alert", "anomalies": anomalies},
            priority=2,
        )
        TaskQueue().push(
            agent="sales",
            payload={"action": "finance_anomaly", "anomalies": anomalies},
            priority=3,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _days_ago(days: int) -> int:
        import time
        return int(time.time()) - days * 86400
