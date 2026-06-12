"""Supabase connector — PostgREST data API + auth admin."""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from .base_connector import BaseConnector


class SupabaseConnector(BaseConnector):
    service_name = "supabase"
    _rate_limit_config = (120, 60)  # conservative for Management API

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {
            "url": settings.SUPABASE_URL,
            "key": settings.SUPABASE_SERVICE_ROLE_KEY,
        }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        creds = self.load_credentials()
        self._url = creds["url"].rstrip("/")
        self._headers = {
            "apikey": creds["key"],
            "Authorization": f"Bearer {creds['key']}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # PostgREST data API
    # ------------------------------------------------------------------

    def query(
        self,
        table: str,
        select: str = "*",
        filters: dict[str, str] | None = None,
        limit: int = 100,
        order: str | None = None,
    ) -> list[dict]:
        params: dict[str, Any] = {"select": select, "limit": limit}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        resp = self.request(
            "GET",
            f"{self._url}/rest/v1/{table}",
            headers={**self._headers, "Prefer": "return=representation"},
            params=params,
        )
        return resp.json()

    def insert(self, table: str, data: dict | list[dict]) -> list[dict]:
        resp = self.request(
            "POST",
            f"{self._url}/rest/v1/{table}",
            headers={**self._headers, "Prefer": "return=representation"},
            json=data,
        )
        return resp.json()

    def update(self, table: str, data: dict, filters: dict[str, str]) -> list[dict]:
        resp = self.request(
            "PATCH",
            f"{self._url}/rest/v1/{table}",
            headers={**self._headers, "Prefer": "return=representation"},
            params=filters,
            json=data,
        )
        return resp.json()

    def delete(self, table: str, filters: dict[str, str]) -> list[dict]:
        resp = self.request(
            "DELETE",
            f"{self._url}/rest/v1/{table}",
            headers={**self._headers, "Prefer": "return=representation"},
            params=filters,
        )
        return resp.json()

    def rpc(self, function_name: str, params: dict | None = None) -> Any:
        resp = self.request(
            "POST",
            f"{self._url}/rest/v1/rpc/{function_name}",
            headers=self._headers,
            json=params or {},
        )
        return resp.json()

    # ------------------------------------------------------------------
    # Auth admin
    # ------------------------------------------------------------------

    def create_user(
        self,
        email: str,
        password: str,
        user_metadata: dict | None = None,
    ) -> dict:
        body: dict[str, Any] = {"email": email, "password": password}
        if user_metadata:
            body["user_metadata"] = user_metadata
        resp = self.request(
            "POST",
            f"{self._url}/auth/v1/admin/users",
            headers=self._headers,
            json=body,
        )
        return resp.json()

    def delete_user(self, user_id: str) -> dict:
        resp = self.request(
            "DELETE",
            f"{self._url}/auth/v1/admin/users/{user_id}",
            headers=self._headers,
        )
        return resp.json()
