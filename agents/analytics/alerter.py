"""Anomaly detection + Slack/email alerts for significant metric changes."""
from __future__ import annotations

from typing import TYPE_CHECKING

from shared.config.settings import settings
from shared.logger import get_logger

if TYPE_CHECKING:
    from .db import AnalyticsDB

logger = get_logger(__name__)

_DIRECTION = {True: "↓", False: "↑"}
_COLOR = {True: "#CC0000", False: "#00AA44"}


class AnalyticsAlerter:
    def __init__(self, db: "AnalyticsDB") -> None:
        self._db = db
        self._threshold = settings.ANALYTICS_ANOMALY_THRESHOLD

    def check_and_alert(self, current_metrics: dict[str, float]) -> list[dict]:
        anomalies: list[dict] = []
        for metric_type, current_value in current_metrics.items():
            baseline = self._db.get_metric_average(metric_type, days=7)
            if baseline is None or baseline == 0:
                continue
            change_pct = (current_value - baseline) / abs(baseline)
            if abs(change_pct) < self._threshold:
                continue
            anomaly = {
                "metric": metric_type,
                "current": current_value,
                "baseline_7d_avg": baseline,
                "change_pct": change_pct,
            }
            anomalies.append(anomaly)
            self._db.insert_anomaly(
                metric_type=metric_type,
                current_val=current_value,
                baseline_val=baseline,
                change_pct=change_pct,
                alerted=bool(settings.ANALYTICS_SLACK_CHANNEL),
            )

        if anomalies and settings.ANALYTICS_SLACK_CHANNEL:
            self._send_slack(anomalies)

        return anomalies

    def _send_slack(self, anomalies: list[dict]) -> None:
        try:
            from agents.integrations.connectors.slack import SlackConnector

            slack = SlackConnector(called_by="analytics", method_name="anomaly_alert")
            is_bad = any(a["change_pct"] < 0 for a in anomalies)
            lines = []
            for a in anomalies:
                neg = a["change_pct"] < 0
                lines.append(
                    f"• *{a['metric']}*: {_DIRECTION[neg]} {abs(a['change_pct'])*100:.1f}% "
                    f"(7d avg {a['baseline_7d_avg']:.1f} → now {a['current']:.1f})"
                )
            slack.post_alert(
                channel=settings.ANALYTICS_SLACK_CHANNEL,
                title="Analytics Anomaly Detected",
                message="\n".join(lines),
                color=_COLOR[is_bad],
            )
            logger.info("anomaly_alert_sent", count=len(anomalies))
        except Exception as exc:
            logger.warning("anomaly_alert_failed", error=str(exc))
