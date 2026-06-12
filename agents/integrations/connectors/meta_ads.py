"""Meta Ads (Facebook / Instagram) Graph API connector."""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from .base_connector import BaseConnector

_BASE = "https://graph.facebook.com/v19.0"


class MetaAdsConnector(BaseConnector):
    service_name = "meta_ads"
    _rate_limit_config = (200, 3600)  # ~200 calls/hour per user token

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {
            "access_token": settings.META_ACCESS_TOKEN,
            "ad_account_id": settings.META_AD_ACCOUNT_ID,
        }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        creds = self.load_credentials()
        self._token = creds["access_token"]
        act = creds["ad_account_id"]
        self._act = act if act.startswith("act_") else f"act_{act}"

    def _params(self, extra: dict | None = None) -> dict:
        base: dict[str, Any] = {"access_token": self._token}
        if extra:
            base.update(extra)
        return base

    # ------------------------------------------------------------------

    def create_campaign(
        self,
        name: str,
        objective: str,
        status: str = "PAUSED",
        special_ad_categories: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "name": name,
            "objective": objective,
            "status": status,
            "special_ad_categories": special_ad_categories or [],
        }
        resp = self.request("POST", f"{_BASE}/{self._act}/campaigns", params=self._params(), json=body)
        return resp.json()

    def create_ad_set(
        self,
        campaign_id: str,
        name: str,
        daily_budget_cents: int,
        billing_event: str,
        optimization_goal: str,
        targeting: dict,
    ) -> dict:
        body: dict[str, Any] = {
            "campaign_id": campaign_id,
            "name": name,
            "daily_budget": daily_budget_cents,
            "billing_event": billing_event,
            "optimization_goal": optimization_goal,
            "targeting": targeting,
            "status": "PAUSED",
        }
        resp = self.request("POST", f"{_BASE}/{self._act}/adsets", params=self._params(), json=body)
        return resp.json()

    def create_ad(
        self,
        ad_set_id: str,
        name: str,
        creative_id: str,
        status: str = "PAUSED",
    ) -> dict:
        body = {
            "adset_id": ad_set_id,
            "name": name,
            "creative": {"creative_id": creative_id},
            "status": status,
        }
        resp = self.request("POST", f"{_BASE}/{self._act}/ads", params=self._params(), json=body)
        return resp.json()

    def get_campaign_insights(
        self,
        campaign_id: str,
        fields: list[str] | None = None,
        date_preset: str = "last_7d",
    ) -> dict:
        default_fields = ["impressions", "clicks", "spend", "cpm", "ctr", "conversions"]
        resp = self.request(
            "GET",
            f"{_BASE}/{campaign_id}/insights",
            params=self._params({
                "fields": ",".join(fields or default_fields),
                "date_preset": date_preset,
            }),
        )
        return resp.json()

    def pause_campaign(self, campaign_id: str) -> dict:
        resp = self.request(
            "POST",
            f"{_BASE}/{campaign_id}",
            params=self._params({"status": "PAUSED"}),
        )
        return resp.json()

    def resume_campaign(self, campaign_id: str) -> dict:
        resp = self.request(
            "POST",
            f"{_BASE}/{campaign_id}",
            params=self._params({"status": "ACTIVE"}),
        )
        return resp.json()

    def list_campaigns(self, status: str = "ACTIVE", limit: int = 20) -> list[dict]:
        resp = self.request(
            "GET",
            f"{_BASE}/{self._act}/campaigns",
            params=self._params({
                "fields": "id,name,status,objective,daily_budget",
                "filtering": f'[{{"field":"effective_status","operator":"IN","value":["{status}"]}}]',
                "limit": limit,
            }),
        )
        return resp.json().get("data", [])

    def create_audience(
        self,
        name: str,
        description: str,
        rule: dict,
    ) -> dict:
        body = {
            "name": name,
            "description": description,
            "rule": rule,
            "subtype": "CUSTOM",
        }
        resp = self.request(
            "POST",
            f"{_BASE}/{self._act}/customaudiences",
            params=self._params(),
            json=body,
        )
        return resp.json()

    def get_account_insights(self, date_preset: str = "last_30d") -> dict:
        resp = self.request(
            "GET",
            f"{_BASE}/{self._act}/insights",
            params=self._params({
                "fields": "impressions,clicks,spend,conversions,cpm,ctr",
                "date_preset": date_preset,
            }),
        )
        return resp.json()
