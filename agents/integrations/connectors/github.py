"""GitHub REST API v3 connector."""
from __future__ import annotations

import base64
from typing import Any

from shared.config.settings import settings

from .base_connector import BaseConnector

_BASE = "https://api.github.com"


class GitHubConnector(BaseConnector):
    service_name = "github"
    _rate_limit_config = (5000, 3600)  # 5 000 requests/hour per token

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {"token": settings.GITHUB_TOKEN, "org": settings.GITHUB_ORG}

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        creds = self.load_credentials()
        self._org = creds["org"]
        self._headers = {
            "Authorization": f"Bearer {creds['token']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ------------------------------------------------------------------

    def create_issue(
        self,
        repo: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        resp = self.request("POST", f"{_BASE}/repos/{self._org}/{repo}/issues", json=payload, headers=self._headers)
        return resp.json()

    def close_issue(self, repo: str, number: int) -> dict:
        resp = self.request(
            "PATCH",
            f"{_BASE}/repos/{self._org}/{repo}/issues/{number}",
            json={"state": "closed"},
            headers=self._headers,
        )
        return resp.json()

    def list_prs(self, repo: str, state: str = "open") -> list[dict]:
        resp = self.request(
            "GET",
            f"{_BASE}/repos/{self._org}/{repo}/pulls",
            params={"state": state, "per_page": 50},
            headers=self._headers,
        )
        return resp.json()

    def merge_pr(self, repo: str, number: int, commit_title: str = "") -> dict:
        payload: dict[str, Any] = {"merge_method": "squash"}
        if commit_title:
            payload["commit_title"] = commit_title
        resp = self.request(
            "PUT",
            f"{_BASE}/repos/{self._org}/{repo}/pulls/{number}/merge",
            json=payload,
            headers=self._headers,
        )
        return resp.json()

    def create_release(
        self,
        repo: str,
        tag: str,
        name: str,
        body: str = "",
        draft: bool = False,
    ) -> dict:
        resp = self.request(
            "POST",
            f"{_BASE}/repos/{self._org}/{repo}/releases",
            json={"tag_name": tag, "name": name, "body": body, "draft": draft},
            headers=self._headers,
        )
        return resp.json()

    def push_file(
        self,
        repo: str,
        path: str,
        content: str,
        message: str,
        branch: str = "main",
    ) -> dict:
        encoded = base64.b64encode(content.encode()).decode()
        payload: dict[str, Any] = {"message": message, "content": encoded, "branch": branch}
        # If file exists, include its SHA so GitHub treats it as an update
        try:
            existing = self.request(
                "GET",
                f"{_BASE}/repos/{self._org}/{repo}/contents/{path}",
                params={"ref": branch},
                headers=self._headers,
            )
            payload["sha"] = existing.json().get("sha", "")
        except Exception:
            pass
        resp = self.request(
            "PUT",
            f"{_BASE}/repos/{self._org}/{repo}/contents/{path}",
            json=payload,
            headers=self._headers,
        )
        return resp.json()

    def get_file(self, repo: str, path: str, branch: str = "main") -> dict:
        resp = self.request(
            "GET",
            f"{_BASE}/repos/{self._org}/{repo}/contents/{path}",
            params={"ref": branch},
            headers=self._headers,
        )
        data = resp.json()
        if data.get("encoding") == "base64":
            data["decoded_content"] = base64.b64decode(data["content"].replace("\n", "")).decode()
        return data

    def list_collaborators(self, repo: str | None = None) -> list[dict]:
        """List all collaborators across org repos (or a single repo)."""
        if repo:
            resp = self.request(
                "GET",
                f"{_BASE}/repos/{self._org}/{repo}/collaborators",
                params={"per_page": 100},
                headers=self._headers,
            )
            return resp.json()
        resp = self.request(
            "GET",
            f"{_BASE}/orgs/{self._org}/members",
            params={"per_page": 100, "role": "all"},
            headers=self._headers,
        )
        return resp.json()
