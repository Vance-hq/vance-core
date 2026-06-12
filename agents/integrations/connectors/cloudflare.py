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

    def block_ip_access_rule(self, zone_id: str, ip: str, mode: str = "block", notes: str = "") -> dict:
        """Create an IP access rule to block a specific address."""
        resp = self.request(
            "POST",
            f"{_BASE}/zones/{zone_id}/firewall/access_rules/rules",
            json={"mode": mode, "configuration": {"target": "ip", "value": ip}, "notes": notes},
            headers=self._headers,
        )
        return resp.json()

    def list_access_rules(self, zone_id: str, mode: str | None = None) -> list[dict]:
        """List IP access rules for a zone."""
        params: dict[str, Any] = {"per_page": 100}
        if mode:
            params["mode"] = mode
        resp = self.request(
            "GET",
            f"{_BASE}/zones/{zone_id}/firewall/access_rules/rules",
            params=params,
            headers=self._headers,
        )
        return resp.json().get("result", [])

    def set_zone_security_level(self, zone_id: str, level: str) -> dict:
        """Set security level: under_attack | high | medium | low | essentially_off."""
        resp = self.request(
            "PATCH",
            f"{_BASE}/zones/{zone_id}/settings/security_level",
            json={"value": level},
            headers=self._headers,
        )
        return resp.json()

    def create_custom_firewall_rule(
        self,
        zone_id: str,
        expression: str,
        action: str,
        description: str = "",
    ) -> dict:
        """Create a WAF custom rule (Cloudflare Ruleset API)."""
        resp = self.request(
            "POST",
            f"{_BASE}/zones/{zone_id}/firewall/rules",
            json=[{
                "action": action,
                "description": description,
                "filter": {"expression": expression},
            }],
            headers=self._headers,
        )
        return resp.json()

    def list_account_members(self) -> list[dict]:
        """List all members of the Cloudflare account."""
        from shared.config.settings import settings as _settings
        resp = self.request(
            "GET",
            f"{_BASE}/accounts/{_settings.CLOUDFLARE_ACCOUNT_ID}/members",
            params={"per_page": 100},
            headers=self._headers,
        )
        return resp.json().get("result", [])
