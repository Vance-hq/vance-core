"""Google Workspace connector (Gmail + Drive + Docs via OAuth2)."""
from __future__ import annotations

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from shared.config.settings import settings

from ._google_auth import get_google_access_token
from .base_connector import BaseConnector

_GMAIL = "https://gmail.googleapis.com/gmail/v1"
_DRIVE = "https://www.googleapis.com/drive/v3"
_DOCS = "https://docs.googleapis.com/v1"


class GoogleWorkspaceConnector(BaseConnector):
    service_name = "google_workspace"
    _rate_limit_config = (250, 100)  # 250 queries per 100 seconds per user

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {"refresh_token": settings.GOOGLE_WORKSPACE_REFRESH_TOKEN}

    def _token(self) -> str:
        return get_google_access_token(self._redis, "workspace", settings.GOOGLE_WORKSPACE_REFRESH_TOKEN)

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}"}

    # ------------------------------------------------------------------
    # Gmail
    # ------------------------------------------------------------------

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        html: bool = False,
    ) -> dict:
        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg.attach(MIMEText(body, "html" if html else "plain"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        resp = self.request(
            "POST",
            f"{_GMAIL}/users/me/messages/send",
            headers={**self._auth(), "Content-Type": "application/json"},
            json={"raw": raw},
        )
        return resp.json()

    def list_emails(self, query: str = "", max_results: int = 10) -> list[dict]:
        params: dict[str, Any] = {"maxResults": max_results}
        if query:
            params["q"] = query
        resp = self.request("GET", f"{_GMAIL}/users/me/messages", headers=self._auth(), params=params)
        return resp.json().get("messages", [])

    def get_email(self, message_id: str) -> dict:
        resp = self.request("GET", f"{_GMAIL}/users/me/messages/{message_id}", headers=self._auth())
        return resp.json()

    def create_draft(self, to: str, subject: str, body: str) -> dict:
        msg = MIMEText(body, "plain")
        msg["To"] = to
        msg["Subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        resp = self.request(
            "POST",
            f"{_GMAIL}/users/me/drafts",
            headers={**self._auth(), "Content-Type": "application/json"},
            json={"message": {"raw": raw}},
        )
        return resp.json()

    # ------------------------------------------------------------------
    # Drive
    # ------------------------------------------------------------------

    def list_drive_files(self, query: str = "", page_size: int = 10) -> list[dict]:
        params: dict[str, Any] = {"pageSize": page_size, "fields": "files(id,name,mimeType,createdTime)"}
        if query:
            params["q"] = query
        resp = self.request("GET", f"{_DRIVE}/files", headers=self._auth(), params=params)
        return resp.json().get("files", [])

    # ------------------------------------------------------------------
    # Docs
    # ------------------------------------------------------------------

    def create_doc(self, title: str, body_text: str = "") -> dict:
        resp = self.request(
            "POST",
            f"{_DOCS}/documents",
            headers={**self._auth(), "Content-Type": "application/json"},
            json={"title": title},
        )
        doc = resp.json()
        if body_text:
            self.append_to_doc(doc["documentId"], body_text)
        return doc

    def get_doc(self, document_id: str) -> dict:
        resp = self.request("GET", f"{_DOCS}/documents/{document_id}", headers=self._auth())
        return resp.json()

    def append_to_doc(self, document_id: str, text: str) -> dict:
        resp = self.request(
            "POST",
            f"{_DOCS}/documents/{document_id}:batchUpdate",
            headers={**self._auth(), "Content-Type": "application/json"},
            json={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": 1},
                            "text": text,
                        }
                    }
                ]
            },
        )
        return resp.json()
