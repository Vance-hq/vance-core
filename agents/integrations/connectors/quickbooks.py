"""QuickBooks Online API v3 connector (OAuth2 refresh-token flow)."""
from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from shared.config.settings import settings
from shared.logger import get_logger

from .base_connector import BaseConnector

logger = get_logger(__name__)
_QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"


class QuickBooksConnector(BaseConnector):
    service_name = "quickbooks"
    _rate_limit_config = (500, 60)

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {
            "client_id": settings.QB_CLIENT_ID,
            "client_secret": settings.QB_CLIENT_SECRET,
            "realm_id": settings.QB_REALM_ID,
            "refresh_token": settings.QB_REFRESH_TOKEN,
        }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._creds = self.load_credentials()
        self._base = f"https://quickbooks.api.intuit.com/v3/company/{self._creds['realm_id']}"

    def _access_token(self) -> str:
        cache_key = "vance:qb_access_token"
        cached = self._redis.get(cache_key)
        if cached:
            return cached  # type: ignore[return-value]
        auth = base64.b64encode(
            f"{self._creds['client_id']}:{self._creds['client_secret']}".encode()
        ).decode()
        resp = httpx.post(
            _QB_TOKEN_URL,
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
            data={"grant_type": "refresh_token", "refresh_token": self._creds["refresh_token"]},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        token: str = data["access_token"]
        self._redis.setex(cache_key, max(60, data.get("expires_in", 3600) - 60), token)
        return token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------

    def get_profit_loss(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        resp = self.request(
            "GET",
            f"{self._base}/reports/ProfitAndLoss",
            params=params,
            headers=self._headers(),
        )
        return resp.json()

    def list_invoices(self, status: str = "Open", limit: int = 20) -> list[dict]:
        query = f"SELECT * FROM Invoice WHERE TxnStatus='{status}' MAXRESULTS {limit}"
        resp = self.request(
            "GET",
            f"{self._base}/query",
            params={"query": query},
            headers=self._headers(),
        )
        return resp.json().get("QueryResponse", {}).get("Invoice", [])

    def get_balance_sheet(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        resp = self.request(
            "GET",
            f"{self._base}/reports/BalanceSheet",
            params=params,
            headers=self._headers(),
        )
        return resp.json()

    def create_expense(
        self,
        account_ref: str,
        amount: float,
        description: str = "",
        vendor_name: str = "",
    ) -> dict:
        body: dict[str, Any] = {
            "PaymentType": "Cash",
            "AccountRef": {"value": account_ref},
            "TotalAmt": amount,
            "Line": [
                {
                    "Amount": amount,
                    "DetailType": "AccountBasedExpenseLineDetail",
                    "AccountBasedExpenseLineDetail": {
                        "AccountRef": {"value": account_ref},
                        "BillableStatus": "NotBillable",
                    },
                    "Description": description,
                }
            ],
        }
        if vendor_name:
            body["EntityRef"] = {"name": vendor_name, "type": "Vendor"}
        resp = self.request("POST", f"{self._base}/purchase", json=body, headers=self._headers())
        return resp.json().get("Purchase", {})

    def sync_stripe_revenue(self, revenue_data: list[dict]) -> list[dict]:
        """Create journal entries from Stripe revenue items."""
        results = []
        for item in revenue_data:
            amount = item.get("amount_cents", 0) / 100.0
            description = item.get("description", "Stripe revenue")
            entry = {
                "JournalEntry": {
                    "TotalAmt": amount,
                    "Line": [
                        {
                            "Amount": amount,
                            "DetailType": "JournalEntryLineDetail",
                            "JournalEntryLineDetail": {
                                "PostingType": "Credit",
                                "AccountRef": {"name": "Sales of Product Income"},
                            },
                            "Description": description,
                        },
                        {
                            "Amount": amount,
                            "DetailType": "JournalEntryLineDetail",
                            "JournalEntryLineDetail": {
                                "PostingType": "Debit",
                                "AccountRef": {"name": "Checking"},
                            },
                            "Description": description,
                        },
                    ],
                }
            }
            resp = self.request("POST", f"{self._base}/journalentry", json=entry, headers=self._headers())
            results.append(resp.json())
        return results
