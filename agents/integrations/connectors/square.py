"""Square Payments API v2 connector."""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from .base_connector import BaseConnector


class SquareConnector(BaseConnector):
    service_name = "square"
    _rate_limit_config = (100, 60)

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {
            "token": settings.SQUARE_ACCESS_TOKEN,
            "env": settings.SQUARE_ENVIRONMENT,
        }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        creds = self.load_credentials()
        base = "https://connect.squareup.com" if creds["env"] == "production" else "https://connect.squareupsandbox.com"
        self._base = f"{base}/v2"
        self._headers = {
            "Authorization": f"Bearer {creds['token']}",
            "Content-Type": "application/json",
            "Square-Version": "2024-01-17",
        }

    # ------------------------------------------------------------------

    def list_transactions(
        self,
        location_id: str,
        begin_time: str | None = None,
        end_time: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        params: dict[str, Any] = {"location_id": location_id, "limit": limit}
        if begin_time:
            params["begin_time"] = begin_time
        if end_time:
            params["end_time"] = end_time
        resp = self.request("GET", f"{self._base}/payments", params=params, headers=self._headers)
        return resp.json().get("payments", [])

    def get_customer(self, customer_id: str) -> dict:
        resp = self.request("GET", f"{self._base}/customers/{customer_id}", headers=self._headers)
        return resp.json().get("customer", {})

    def create_invoice(
        self,
        location_id: str,
        order_id: str,
        customer_id: str,
        payment_requests: list[dict],
    ) -> dict:
        resp = self.request(
            "POST",
            f"{self._base}/invoices",
            headers=self._headers,
            json={
                "invoice": {
                    "location_id": location_id,
                    "order_id": order_id,
                    "primary_recipient": {"customer_id": customer_id},
                    "payment_requests": payment_requests,
                }
            },
        )
        return resp.json().get("invoice", {})

    def list_locations(self) -> list[dict]:
        resp = self.request("GET", f"{self._base}/locations", headers=self._headers)
        return resp.json().get("locations", [])

    def get_sales_summary(
        self,
        location_id: str,
        begin_time: str | None = None,
        end_time: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "location_ids": [location_id],
            "query": {"sort": {"sort_field": "CREATED_AT", "sort_order": "DESC"}},
            "limit": 100,
        }
        if begin_time or end_time:
            body["query"]["filter"] = {"date_time_filter": {}}
            if begin_time:
                body["query"]["filter"]["date_time_filter"]["created_at"] = {"start_at": begin_time}
            if end_time:
                body["query"]["filter"]["date_time_filter"].setdefault("created_at", {})
                body["query"]["filter"]["date_time_filter"]["created_at"]["end_at"] = end_time
        resp = self.request("POST", f"{self._base}/orders/search", headers=self._headers, json=body)
        orders = resp.json().get("orders", [])
        total_cents = sum(
            o.get("total_money", {}).get("amount", 0) for o in orders
        )
        return {"total_cents": total_cents, "order_count": len(orders), "orders": orders}
