"""Cloudflare REST API connector."""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from .base_connector import BaseConnector

_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareConnector(BaseConnector):
    service_name = "cloudflare"
    _rate_limit_config = (1200, 300)  # 1 200 requests per 5 min

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {
            "token": settings.CLOUDFLARE_API_TOKEN,
            "account_id": settings.CLOUDFLARE_ACCOUNT_ID,
        }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        creds = self.load_credentials()
        self._headers = {"Authorization": f"Bearer {creds['token']}"}

    # ------------------------------------------------------------------

    def purge_cache(self, zone_id: str, files: list[str] | None = None) -> dict:
        body: dict[str, Any] = {"purge_everything": True} if not files else {"files": files}
        resp = self.request(
            "POST",
            f"{_BASE}/zones/{zone_id}/purge_cache",
            json=body,
            headers=self._headers,
        )
        return resp.json()

    def create_dns_record(
        self,
        zone_id: str,
        type: str,
        name: str,
        content: str,
        ttl: int = 1,
        proxied: bool = True,
    ) -> dict:
        resp = self.request(
            "POST",
            f"{_BASE}/zones/{zone_id}/dns_records",
            json={"type": type, "name": name, "content": content, "ttl": ttl, "proxied": proxied},
            headers=self._headers,
        )
        return resp.json()

    def update_dns_record(self, zone_id: str, record_id: str, **fields: Any) -> dict:
        resp = self.request(
            "PATCH",
            f"{_BASE}/zones/{zone_id}/dns_records/{record_id}",
            json=fields,
            headers=self._headers,
        )
        return resp.json()

    def get_analytics(self, zone_id: str, since: str = "-1440") -> dict:
        resp = self.request(
            "GET",
            f"{_BASE}/zones/{zone_id}/analytics/dashboard",
            params={"since": since, "continuous": "false"},
            headers=self._headers,
        )
        return resp.json()

    def create_page_rule(self, zone_id: str, url: str, actions: list[dict]) -> dict:
        resp = self.request(
            "POST",
            f"{_BASE}/zones/{zone_id}/pagerules",
            json={"targets": [{"target": "url", "constraint": {"operator": "matches", "value": url}}], "actions": actions, "status": "active"},
            headers=self._headers,
        )
        return resp.json()
