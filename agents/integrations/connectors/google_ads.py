"""Google Ads API v17 connector."""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from ._google_auth import get_google_access_token
from .base_connector import BaseConnector

_BASE = "https://googleads.googleapis.com/v17"


class GoogleAdsConnector(BaseConnector):
    service_name = "google_ads"
    _rate_limit_config = (1000, 60)

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {
            "refresh_token": settings.GOOGLE_ADS_REFRESH_TOKEN,
            "developer_token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
            "customer_id": settings.GOOGLE_ADS_CUSTOMER_ID,
        }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        creds = self.load_credentials()
        self._cid = creds["customer_id"].replace("-", "")
        self._dev_token = creds["developer_token"]

    def _token(self) -> str:
        return get_google_access_token(self._redis, "ads", settings.GOOGLE_ADS_REFRESH_TOKEN)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token()}",
            "developer-token": self._dev_token,
            "Content-Type": "application/json",
        }

    def _mutate(self, resource: str, operations: list[dict]) -> dict:
        resp = self.request(
            "POST",
            f"{_BASE}/customers/{self._cid}/{resource}:mutate",
            headers=self._headers(),
            json={"operations": operations},
        )
        return resp.json()

    def _search(self, query: str) -> list[dict]:
        resp = self.request(
            "POST",
            f"{_BASE}/customers/{self._cid}/googleAds:search",
            headers=self._headers(),
            json={"query": query},
        )
        return resp.json().get("results", [])

    # ------------------------------------------------------------------

    def create_campaign(
        self,
        name: str,
        budget_micros: int,
        start_date: str | None = None,
    ) -> dict:
        budget_op = {
            "create": {
                "name": f"{name} Budget",
                "amount_micros": budget_micros,
                "delivery_method": "STANDARD",
            }
        }
        budget_resp = self._mutate("campaignBudgets", [budget_op])
        resource_name = budget_resp.get("results", [{}])[0].get("resourceName", "")
        campaign_op: dict[str, Any] = {
            "create": {
                "name": name,
                "status": "PAUSED",
                "advertising_channel_type": "SEARCH",
                "campaign_budget": resource_name,
                "bidding_strategy_type": "MANUAL_CPC",
            }
        }
        if start_date:
            campaign_op["create"]["start_date"] = start_date
        return self._mutate("campaigns", [campaign_op])

    def pause_campaign(self, campaign_resource_name: str) -> dict:
        return self._mutate("campaigns", [{"update": {"resource_name": campaign_resource_name, "status": "PAUSED"}, "update_mask": {"paths": ["status"]}}])

    def update_budget(self, campaign_budget_resource_name: str, amount_micros: int) -> dict:
        return self._mutate("campaignBudgets", [{"update": {"resource_name": campaign_budget_resource_name, "amount_micros": amount_micros}, "update_mask": {"paths": ["amount_micros"]}}])

    def get_performance(
        self,
        campaign_ids: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        date_clause = ""
        if start_date and end_date:
            date_clause = f" AND segments.date BETWEEN '{start_date}' AND '{end_date}'"
        id_clause = ""
        if campaign_ids:
            id_list = ", ".join(f"'{i}'" for i in campaign_ids)
            id_clause = f" AND campaign.id IN ({id_list})"
        query = (
            "SELECT campaign.id, campaign.name, campaign.status, "
            "metrics.impressions, metrics.clicks, metrics.conversions, metrics.cost_micros "
            f"FROM campaign WHERE campaign.status != 'REMOVED'{date_clause}{id_clause}"
        )
        return self._search(query)

    def create_ad_group(
        self,
        campaign_resource_name: str,
        name: str,
        cpc_bid_micros: int | None = None,
    ) -> dict:
        create: dict[str, Any] = {
            "name": name,
            "status": "ENABLED",
            "campaign": campaign_resource_name,
        }
        if cpc_bid_micros:
            create["cpc_bid_micros"] = cpc_bid_micros
        return self._mutate("adGroups", [{"create": create}])

    def add_keywords(self, ad_group_resource_name: str, keywords: list[str]) -> dict:
        ops = [
            {
                "create": {
                    "ad_group": ad_group_resource_name,
                    "keyword": {"text": kw, "match_type": "BROAD"},
                    "status": "ENABLED",
                }
            }
            for kw in keywords
        ]
        return self._mutate("adGroupCriteria", ops)

    def get_search_terms_report(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        date_clause = ""
        if start_date and end_date:
            date_clause = f" WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'"
        return self._search(
            "SELECT search_term_view.search_term, metrics.impressions, metrics.clicks, metrics.conversions "
            f"FROM search_term_view{date_clause} ORDER BY metrics.impressions DESC LIMIT 100"
        )
