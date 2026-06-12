"""Email sender for support agent using Resend API."""

from __future__ import annotations

from typing import Any

import httpx

from shared.logger import get_logger

logger = get_logger(__name__)

_RESEND_URL = "https://api.resend.com/emails"


def send_email(
    *,
    api_key: str,
    to: str,
    from_email: str,
    from_name: str,
    subject: str,
    html: str,
) -> bool:
    try:
        resp = httpx.post(
            _RESEND_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": f"{from_name} <{from_email}>",
                "to": [to],
                "subject": subject,
                "html": html,
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return True
        logger.warning("resend_send_failed", status=resp.status_code, preview=resp.text[:80])
        return False
    except Exception as exc:
        logger.warning("resend_send_error", error=str(exc))
        return False
