"""HTTP client for the Forge internal API (/repos/forge)."""

from __future__ import annotations

from typing import Any

import httpx

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)


class ForgeAPIClient:
    """Thin wrapper around the Forge REST API."""

    def __init__(self) -> None:
        self._base = settings.FORGE_API_URL.rstrip("/")
        self._headers = {"Authorization": f"Bearer {settings.FORGE_API_SECRET}"}

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        resp = httpx.get(f"{self._base}{path}", headers=self._headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = httpx.patch(f"{self._base}{path}", headers=self._headers, json=body, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_sequences(self, product: str) -> list[dict[str, Any]]:
        try:
            return self._get("/api/sequences", product=product).get("sequences", [])
        except Exception as exc:
            logger.warning("forge_api_get_sequences_failed", product=product, error=str(exc))
            return []

    def get_sequence(self, sequence_id: str) -> dict[str, Any] | None:
        try:
            return self._get(f"/api/sequences/{sequence_id}")
        except Exception as exc:
            logger.warning("forge_api_get_sequence_failed", id=sequence_id, error=str(exc))
            return None

    def update_sequence_status(self, sequence_id: str, status: str) -> bool:
        try:
            self._patch(f"/api/sequences/{sequence_id}", {"status": status})
            return True
        except Exception as exc:
            logger.warning("forge_api_update_sequence_failed", id=sequence_id, error=str(exc))
            return False
