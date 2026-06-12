"""Slack Web API connector."""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from .base_connector import BaseConnector

_BASE = "https://slack.com/api"


class SlackConnector(BaseConnector):
    service_name = "slack"
    _rate_limit_config = (50, 60)  # Tier 3: ~1/s average; we stay conservative

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {"bot_token": settings.SLACK_BOT_TOKEN}

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._headers = {
            "Authorization": f"Bearer {self.load_credentials()['bot_token']}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _call(self, method: str, **body: Any) -> dict:
        resp = self.request("POST", f"{_BASE}/{method}", headers=self._headers, json=body)
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error ({method}): {data.get('error')}")
        return data

    # ------------------------------------------------------------------

    def send_message(
        self,
        channel: str,
        text: str,
        blocks: list[dict] | None = None,
        thread_ts: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"channel": channel, "text": text}
        if blocks:
            body["blocks"] = blocks
        if thread_ts:
            body["thread_ts"] = thread_ts
        return self._call("chat.postMessage", **body)

    def send_dm(self, user_id: str, text: str, blocks: list[dict] | None = None) -> dict:
        open_resp = self._call("conversations.open", users=user_id)
        channel = open_resp["channel"]["id"]
        return self.send_message(channel, text, blocks=blocks)

    def create_channel(self, name: str, is_private: bool = False) -> dict:
        return self._call("conversations.create", name=name, is_private=is_private)

    def upload_file(
        self,
        channel: str,
        filename: str,
        content: str,
        filetype: str = "text",
        title: str = "",
    ) -> dict:
        return self._call(
            "files.upload",
            channels=channel,
            filename=filename,
            content=content,
            filetype=filetype,
            title=title or filename,
        )

    def set_status(self, text: str, emoji: str = "", expiration: int = 0) -> dict:
        return self._call(
            "users.profile.set",
            profile={
                "status_text": text,
                "status_emoji": emoji,
                "status_expiration": expiration,
            },
        )

    def post_alert(
        self,
        channel: str,
        title: str,
        message: str,
        color: str = "#FF0000",
    ) -> dict:
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{title}*\n{message}"},
            }
        ]
        return self.send_message(channel, f"{title}: {message}", blocks=blocks)

    def list_channels(self, limit: int = 100, exclude_archived: bool = True) -> list[dict]:
        resp = self.request(
            "GET",
            f"{_BASE}/conversations.list",
            headers=self._headers,
            params={"limit": limit, "exclude_archived": str(exclude_archived).lower()},
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error')}")
        return data.get("channels", [])
