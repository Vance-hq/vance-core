"""AlertBroadcaster — immediate broadcast of critical alerts to configured channels."""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger

logger = get_logger(__name__)


class AlertBroadcaster:

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg

    def broadcast(self, title: str, message: str, severity: str, source: str) -> dict[str, Any]:
        channels_hit: list[str] = []

        slack_webhook = self._cfg.get("slack_alert_webhook", "")
        if slack_webhook:
            sent = self._send_slack(webhook=slack_webhook, title=title, message=message, severity=severity)
            if sent:
                channels_hit.append("slack")

        email_recipients = self._cfg.get("alert_email_recipients", [])
        if email_recipients:
            sent = self._send_email(recipients=email_recipients, title=title, message=message)
            if sent:
                channels_hit.append("email")

        logger.info("alert_broadcast", title=title, severity=severity, source=source, channels=channels_hit)
        return {
            "title": title,
            "severity": severity,
            "source": source,
            "channels_notified": channels_hit,
        }

    def _send_slack(self, webhook: str, title: str, message: str, severity: str) -> bool:
        try:
            import httpx
            color = "#CC0000" if severity in ("critical", "high") else "#FFA500"
            payload = {
                "attachments": [{"color": color, "title": title, "text": message, "footer": "Vance Reporting"}]
            }
            resp = httpx.post(webhook, json=payload, timeout=5)
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("slack_alert_failed", error=str(exc))
            return False

    def _send_email(self, recipients: list[str], title: str, message: str) -> bool:
        try:
            import resend  # type: ignore
            api_key = self._cfg.get("resend_api_key", "")
            if not api_key:
                return False
            resend.api_key = api_key
            resend.Emails.send({
                "from": self._cfg.get("from_email", "vance@mail.vance.so"),
                "to": recipients,
                "subject": f"⚠️ {title}",
                "text": message,
            })
            return True
        except Exception as exc:
            logger.warning("alert_email_failed", error=str(exc))
            return False
