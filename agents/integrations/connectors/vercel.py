"""Vercel REST API connector."""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from .base_connector import BaseConnector

_BASE = "https://api.vercel.com"


class VercelConnector(BaseConnector):
    service_name = "vercel"
    _rate_limit_config = (3600, 3600)

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {"token": settings.VERCEL_TOKEN, "team_id": settings.VERCEL_TEAM_ID}

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        creds = self.load_credentials()
        self._headers = {"Authorization": f"Bearer {creds['token']}"}
        self._team_id = creds["team_id"]

    def _params(self, extra: dict | None = None) -> dict:
        base = {"teamId": self._team_id} if self._team_id else {}
        if extra:
            base.update(extra)
        return base

    # ------------------------------------------------------------------

    def trigger_deploy(self, project_id: str, git_ref: str = "main") -> dict:
        resp = self.request(
            "POST",
            f"{_BASE}/v13/deployments",
            json={"name": project_id, "gitSource": {"type": "github", "ref": git_ref}},
            headers=self._headers,
            params=self._params(),
        )
        return resp.json()

    def get_deployment_status(self, deployment_id: str) -> dict:
        resp = self.request(
            "GET",
            f"{_BASE}/v13/deployments/{deployment_id}",
            headers=self._headers,
            params=self._params(),
        )
        return resp.json()

    def rollback(self, project_id: str, deployment_id: str) -> dict:
        resp = self.request(
            "PATCH",
            f"{_BASE}/v1/projects/{project_id}/rollback/{deployment_id}",
            headers=self._headers,
            params=self._params(),
        )
        return resp.json()

    def list_deployments(self, project_id: str, limit: int = 10) -> list[dict]:
        resp = self.request(
            "GET",
            f"{_BASE}/v6/deployments",
            headers=self._headers,
            params=self._params({"projectId": project_id, "limit": limit}),
        )
        return resp.json().get("deployments", [])

    def set_env_var(
        self,
        project_id: str,
        key: str,
        value: str,
        env_type: str = "production",
    ) -> dict:
        resp = self.request(
            "POST",
            f"{_BASE}/v10/projects/{project_id}/env",
            headers=self._headers,
            params=self._params(),
            json={"key": key, "value": value, "type": "encrypted", "target": [env_type]},
        )
        return resp.json()
