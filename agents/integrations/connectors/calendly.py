"""Calendly API v2 connector."""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from .base_connector import BaseConnector

_BASE = "https://api.calendly.com"


class CalendlyConnector(BaseConnector):
    service_name = "calendly"
    _rate_limit_config = (120, 60)

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {"api_token": settings.CALENDLY_API_TOKEN}

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._headers = {
            "Authorization": f"Bearer {self.load_credentials()['api_token']}",
            "Content-Type": "application/json",
        }
        self._user_uri: str | None = None

    def _current_user_uri(self) -> str:
        if not self._user_uri:
            resp = self.request("GET", f"{_BASE}/users/me", headers=self._headers)
            self._user_uri = resp.json().get("resource", {}).get("uri", "")
        return self._user_uri

    # ------------------------------------------------------------------

    def list_event_types(self) -> list[dict]:
        resp = self.request(
            "GET",
            f"{_BASE}/event_types",
            headers=self._headers,
            params={"user": self._current_user_uri()},
        )
        return resp.json().get("collection", [])

    def get_scheduled_events(
        self,
        min_start_time: str | None = None,
        max_start_time: str | None = None,
        status: str = "active",
    ) -> list[dict]:
        params: dict[str, Any] = {"user": self._current_user_uri(), "status": status}
        if min_start_time:
            params["min_start_time"] = min_start_time
        if max_start_time:
            params["max_start_time"] = max_start_time
        resp = self.request("GET", f"{_BASE}/scheduled_events", headers=self._headers, params=params)
        return resp.json().get("collection", [])

    def cancel_event(self, event_uuid: str, reason: str = "") -> dict:
        resp = self.request(
            "POST",
            f"{_BASE}/scheduled_events/{event_uuid}/cancellation",
            headers=self._headers,
            json={"reason": reason},
        )
        return resp.json()

    def create_scheduling_link(
        self,
        max_event_count: int = 1,
        owner: str | None = None,
    ) -> dict:
        resp = self.request(
            "POST",
            f"{_BASE}/scheduling_links",
            headers=self._headers,
            json={
                "max_event_count": max_event_count,
                "owner": owner or self._current_user_uri(),
                "owner_type": "users",
            },
        )
        return resp.json().get("resource", {})

    def get_invitee(self, event_uuid: str, invitee_uuid: str) -> dict:
        resp = self.request(
            "GET",
            f"{_BASE}/scheduled_events/{event_uuid}/invitees/{invitee_uuid}",
            headers=self._headers,
        )
        return resp.json().get("resource", {})

    def list_invitees(self, event_uuid: str) -> list[dict]:
        resp = self.request(
            "GET",
            f"{_BASE}/scheduled_events/{event_uuid}/invitees",
            headers=self._headers,
        )
        return resp.json().get("collection", [])
