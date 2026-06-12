"""CAC, LTV, LTV:CAC ratio, and payback period calculator."""

from __future__ import annotations

from datetime import date

from agents.integrations.connectors.stripe import StripeConnector
from shared.logger import get_logger

from .db import FinanceDB

logger = get_logger(__name__)

MONTHS_TO_CALCULATE_CHURN = 3


class UnitEconomicsCalculator:
    def __init__(self, config: dict, db: FinanceDB | None = None) -> None:
        self._cfg = config
        self._db = db or FinanceDB()
        self._stripe = StripeConnector()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(self, sales_marketing_spend_cents: int, new_customers: int) -> dict:
        """
        Compute and store unit economics for the current month.

        sales_marketing_spend_cents: total S&M spend this month
        new_customers: net new paying customers acquired this month
        """
        period_month = date.today().replace(day=1)

        cac_cents = self._cac(sales_marketing_spend_cents, new_customers)
        arpu_cents, churn_rate = self._arpu_and_churn()
        ltv_cents = self._ltv(arpu_cents, churn_rate)
        ltv_cac_ratio = round(ltv_cents / cac_cents, 2) if cac_cents else 0.0
        payback_months = round(cac_cents / arpu_cents, 2) if arpu_cents else 0.0

        self._db.upsert_unit_economics(
            period_month=period_month,
            cac_cents=cac_cents,
            ltv_cents=ltv_cents,
            ltv_cac_ratio=ltv_cac_ratio,
            payback_months=payback_months,
            new_customers=new_customers,
            sales_marketing_spend_cents=sales_marketing_spend_cents,
            metadata={
                "arpu_cents": arpu_cents,
                "churn_rate": churn_rate,
            },
        )

        return {
            "period_month": str(period_month),
            "cac_cents": cac_cents,
            "cac_usd": cac_cents / 100,
            "ltv_cents": ltv_cents,
            "ltv_usd": ltv_cents / 100,
            "ltv_cac_ratio": ltv_cac_ratio,
            "payback_months": payback_months,
            "arpu_cents": arpu_cents,
            "churn_rate_pct": round(churn_rate * 100, 2),
            "new_customers": new_customers,
        }

    # ------------------------------------------------------------------
    # Private calculations
    # ------------------------------------------------------------------

    def _cac(self, spend: int, new_customers: int) -> int:
        if new_customers <= 0:
            return 0
        return spend // new_customers

    def _arpu_and_churn(self) -> tuple[int, float]:
        """Return (ARPU in cents, monthly churn rate as fraction)."""
        data = self._stripe.get_mrr()
        mrr_cents = data.get("mrr_cents", 0)
        subscriber_count = data.get("subscription_count", 0)

        arpu_cents = (mrr_cents // subscriber_count) if subscriber_count else 0

        # Estimate churn from cancelled subs in last 3 months
        churned = self._estimate_churned_count()
        avg_subs = max(subscriber_count, 1)
        churn_rate = churned / (avg_subs * MONTHS_TO_CALCULATE_CHURN)

        return arpu_cents, churn_rate

    def _ltv(self, arpu_cents: int, churn_rate: float) -> int:
        """LTV = ARPU / churn_rate (simple LTV formula)."""
        if churn_rate <= 0:
            # Default to 36-month lifetime if no churn data
            return arpu_cents * 36
        return int(arpu_cents / churn_rate)

    def _estimate_churned_count(self) -> int:
        """Count cancelled subscriptions in last 3 months."""
        cancelled = self._stripe.list_subscriptions(status="canceled", limit=100)
        import time
        cutoff = int(time.time()) - MONTHS_TO_CALCULATE_CHURN * 30 * 86400
        return len([s for s in cancelled if s.get("canceled_at", 0) >= cutoff])
