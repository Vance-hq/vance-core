"""Twilio REST API connector."""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from .base_connector import BaseConnector


class TwilioConnector(BaseConnector):
    service_name = "twilio"
    _rate_limit_config = (0, 60)  # Twilio throttles per endpoint internally

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {
            "account_sid": settings.TWILIO_ACCOUNT_SID,
            "auth_token": settings.TWILIO_AUTH_TOKEN,
            "from_number": settings.TWILIO_FROM_NUMBER,
        }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        creds = self.load_credentials()
        self._sid = creds["account_sid"]
        self._from = creds["from_number"]
        self._base = f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}"
        self._auth = (creds["account_sid"], creds["auth_token"])

    # ------------------------------------------------------------------

    def send_sms(self, to: str, body: str) -> dict:
        resp = self.request(
            "POST",
            f"{self._base}/Messages.json",
            auth=self._auth,
            data={"To": to, "From": self._from, "Body": body},
        )
        return resp.json()

    def send_mms(self, to: str, body: str, media_url: str) -> dict:
        resp = self.request(
            "POST",
            f"{self._base}/Messages.json",
            auth=self._auth,
            data={"To": to, "From": self._from, "Body": body, "MediaUrl": media_url},
        )
        return resp.json()

    def make_call(self, to: str, twiml_url: str, method: str = "POST") -> dict:
        resp = self.request(
            "POST",
            f"{self._base}/Calls.json",
            auth=self._auth,
            data={"To": to, "From": self._from, "Url": twiml_url, "Method": method},
        )
        return resp.json()

    def get_message_status(self, message_sid: str) -> dict:
        resp = self.request(
            "GET",
            f"{self._base}/Messages/{message_sid}.json",
            auth=self._auth,
        )
        return resp.json()

    def list_messages(self, limit: int = 20, status: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"PageSize": limit}
        if status:
            params["Status"] = status
        resp = self.request(
            "GET",
            f"{self._base}/Messages.json",
            auth=self._auth,
            params=params,
        )
        return resp.json().get("messages", [])

    def get_account_balance(self) -> dict:
        resp = self.request(
            "GET",
            f"{self._base}/Balance.json",
            auth=self._auth,
        )
        return resp.json()
