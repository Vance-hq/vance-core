"""Stripe REST API connector."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from shared.config.settings import settings

from .base_connector import BaseConnector

_BASE = "https://api.stripe.com/v1"


class StripeConnector(BaseConnector):
    service_name = "stripe"
    _rate_limit_config = (25, 1)  # 25 req/s live mode limit

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {"secret_key": settings.STRIPE_SECRET_KEY}

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._headers = {"Authorization": f"Bearer {self.load_credentials()['secret_key']}"}

    def _stripe_params(self, data: dict) -> str:
        """Stripe uses form-encoded bodies, not JSON."""
        return urlencode(data)

    # ------------------------------------------------------------------

    def get_mrr(self) -> dict:
        resp = self.request(
            "GET",
            f"{_BASE}/subscriptions",
            params={"status": "active", "limit": 100},
            headers=self._headers,
        )
        subs = resp.json().get("data", [])
        total_cents = sum(
            (s.get("items", {}).get("data", [{}])[0].get("plan", {}).get("amount", 0) or 0)
            for s in subs
        )
        return {"mrr_cents": total_cents, "subscription_count": len(subs)}

    def list_subscriptions(
        self,
        product: str | None = None,
        status: str = "active",
        limit: int = 100,
    ) -> list[dict]:
        params: dict[str, Any] = {"status": status, "limit": limit}
        if product:
            params["price__product"] = product
        resp = self.request("GET", f"{_BASE}/subscriptions", params=params, headers=self._headers)
        return resp.json().get("data", [])

    def cancel_subscription(self, subscription_id: str) -> dict:
        resp = self.request(
            "DELETE",
            f"{_BASE}/subscriptions/{subscription_id}",
            headers=self._headers,
        )
        return resp.json()

    def update_subscription(self, subscription_id: str, **kwargs: Any) -> dict:
        resp = self.request(
            "POST",
            f"{_BASE}/subscriptions/{subscription_id}",
            headers={**self._headers, "Content-Type": "application/x-www-form-urlencoded"},
            content=self._stripe_params(kwargs).encode(),
        )
        return resp.json()

    def create_coupon(
        self,
        percent_off: int | None = None,
        amount_off: int | None = None,
        currency: str | None = None,
        duration: str = "once",
        name: str = "",
    ) -> dict:
        params: dict[str, Any] = {"duration": duration}
        if name:
            params["name"] = name
        if percent_off is not None:
            params["percent_off"] = percent_off
        if amount_off is not None:
            params["amount_off"] = amount_off
            params["currency"] = currency or "usd"
        resp = self.request(
            "POST",
            f"{_BASE}/coupons",
            headers={**self._headers, "Content-Type": "application/x-www-form-urlencoded"},
            content=self._stripe_params(params).encode(),
        )
        return resp.json()

    def apply_coupon(self, customer_id: str, coupon_id: str) -> dict:
        resp = self.request(
            "POST",
            f"{_BASE}/customers/{customer_id}",
            headers={**self._headers, "Content-Type": "application/x-www-form-urlencoded"},
            content=self._stripe_params({"coupon": coupon_id}).encode(),
        )
        return resp.json()

    def get_customer(self, customer_id: str) -> dict:
        resp = self.request("GET", f"{_BASE}/customers/{customer_id}", headers=self._headers)
        return resp.json()

    def list_invoices(
        self,
        customer_id: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if customer_id:
            params["customer"] = customer_id
        if status:
            params["status"] = status
        resp = self.request("GET", f"{_BASE}/invoices", params=params, headers=self._headers)
        return resp.json().get("data", [])

    def refund_charge(self, charge_id: str, amount: int | None = None) -> dict:
        params: dict[str, Any] = {"charge": charge_id}
        if amount is not None:
            params["amount"] = amount
        resp = self.request(
            "POST",
            f"{_BASE}/refunds",
            headers={**self._headers, "Content-Type": "application/x-www-form-urlencoded"},
            content=self._stripe_params(params).encode(),
        )
        return resp.json()

    def get_revenue_report(self, start_date: int, end_date: int) -> dict:
        """Returns balance transactions for a Unix timestamp range."""
        resp = self.request(
            "GET",
            f"{_BASE}/balance_transactions",
            params={
                "created[gte]": start_date,
                "created[lte]": end_date,
                "type": "charge",
                "limit": 100,
            },
            headers=self._headers,
        )
        txns = resp.json().get("data", [])
        total = sum(t.get("net", 0) for t in txns)
        return {"net_cents": total, "transaction_count": len(txns), "transactions": txns}
