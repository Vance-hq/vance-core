"""AlertDeliverer — immediate priority alert delivery via voice, Slack, and email."""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import ReportingDB

logger = get_logger(__name__)

PRIORITY_ALERT_TYPES = frozenset({
    "production_down",
    "mrr_drop",
    "security_incident",
    "p0_bug",
})


class AlertDeliverer:

    def __init__(self, db: ReportingDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def deliver(
        self,
        source_agent: str,
        alert_type: str,
        message: str,
        severity: str = "high",
    ) -> dict[str, Any]:
        alert_id = self._db.log_alert(
            source_agent=source_agent,
            alert_type=alert_type,
            message=message,
        )

        channels_hit: list[str] = []

        # Voice is always attempted — interrupts regardless of time
        voice_ok = self._deliver_via_voice(alert_type=alert_type, message=message, severity=severity)
        if voice_ok:
            channels_hit.append("voice")

        slack_webhook = self._cfg.get("slack_alert_webhook", "")
        if slack_webhook:
            sent = self._send_slack(
                webhook=slack_webhook,
                alert_type=alert_type,
                message=message,
                severity=severity,
                source=source_agent,
            )
            if sent:
                channels_hit.append("slack")

        email_recipients = self._cfg.get("alert_email_recipients", [])
        if email_recipients:
            sent = self._send_email(
                recipients=email_recipients,
                alert_type=alert_type,
                message=message,
            )
            if sent:
                channels_hit.append("email")

        self._db.mark_alert_delivered(alert_id)

        logger.info(
            "alert_delivered",
            alert_id=alert_id,
            alert_type=alert_type,
            severity=severity,
            source=source_agent,
            channels=channels_hit,
        )
        return {
            "alert_id": alert_id,
            "alert_type": alert_type,
            "severity": severity,
            "source_agent": source_agent,
            "channels_notified": channels_hit,
        }

    def _deliver_via_voice(self, alert_type: str, message: str, severity: str) -> bool:
        try:
            label = alert_type.replace("_", " ").upper()
            text = f"⚠️ Priority alert: {label}. {message}"
            TaskQueue().push(
                "voice",
                {
                    "action": "speak",
                    "text": text,
                    "priority": "urgent",
                    "source": "alert_deliverer",
                    "alert_type": alert_type,
                },
            )
            return True
        except Exception as exc:
            logger.warning("alert_voice_failed", error=str(exc))
            return False

    def _send_slack(
        self,
        webhook: str,
        alert_type: str,
        message: str,
        severity: str,
        source: str,
    ) -> bool:
        try:
            import httpx
            color = "#CC0000" if severity in ("critical", "high") else "#FFA500"
            title = f"⚠️ {alert_type.replace('_', ' ').title()} [{source}]"
            payload = {
                "attachments": [
                    {
                        "color": color,
                        "title": title,
                        "text": message,
                        "footer": "Vance Reporting",
                    }
                ]
            }
            resp = httpx.post(webhook, json=payload, timeout=5)
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("alert_slack_failed", error=str(exc))
            return False

    def _send_email(self, recipients: list[str], alert_type: str, message: str) -> bool:
        try:
            import resend  # type: ignore
            api_key = self._cfg.get("resend_api_key", "")
            if not api_key:
                return False
            resend.api_key = api_key
            resend.Emails.send({
                "from": self._cfg.get("from_email", "vance@mail.vance.so"),
                "to": recipients,
                "subject": f"⚠️ Vance Alert: {alert_type.replace('_', ' ').title()}",
                "text": message,
            })
            return True
        except Exception as exc:
            logger.warning("alert_email_failed", error=str(exc))
            return False
