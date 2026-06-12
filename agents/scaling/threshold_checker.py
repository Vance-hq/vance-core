"""Alert when resource metrics exceed configured thresholds."""

from __future__ import annotations

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import ScalingDB

logger = get_logger(__name__)

# Default thresholds
_DEFAULTS = {
    "cpu_warning_pct": 80.0,
    "cpu_warning_window_min": 5,
    "cpu_critical_pct": 95.0,
    "cpu_critical_window_min": 2,
    "memory_warning_pct": 85.0,
    "disk_warning_pct": 80.0,
    "disk_critical_pct": 90.0,
}


class ThresholdChecker:

    def __init__(self, cfg: dict, db: ScalingDB | None = None) -> None:
        self._db = db or ScalingDB()
        self._thresholds = {**_DEFAULTS, **cfg.get("thresholds", {})}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, snapshot: dict) -> list[dict]:
        """
        Evaluate current snapshot against thresholds.
        Returns list of fired alerts: {metric, level, value, message}.
        """
        host = snapshot.get("host", {})
        alerts = []

        alerts.extend(self._check_cpu(host.get("cpu_pct", 0.0)))
        alerts.extend(self._check_memory(host.get("memory_pct", 0.0)))
        alerts.extend(self._check_disk(host.get("disk_pct", 0.0)))

        for alert in alerts:
            self._dispatch_alert(alert)

        return alerts

    # ------------------------------------------------------------------
    # Per-metric checks
    # ------------------------------------------------------------------

    def _check_cpu(self, current_pct: float) -> list[dict]:
        alerts = []
        crit_pct = self._thresholds["cpu_critical_pct"]
        crit_win = self._thresholds["cpu_critical_window_min"]
        warn_pct = self._thresholds["cpu_warning_pct"]
        warn_win = self._thresholds["cpu_warning_window_min"]

        if current_pct >= crit_pct:
            # Sustained check: all readings in window must exceed threshold
            if self._sustained_above("cpu_pct", crit_pct, crit_win):
                alerts.append({
                    "metric": "cpu_pct",
                    "level": "CRITICAL",
                    "value": current_pct,
                    "message": (
                        f"CPU at {current_pct:.1f}% for >{crit_win}min "
                        f"(threshold {crit_pct}%)"
                    ),
                })
        elif current_pct >= warn_pct:
            if self._sustained_above("cpu_pct", warn_pct, warn_win):
                alerts.append({
                    "metric": "cpu_pct",
                    "level": "WARNING",
                    "value": current_pct,
                    "message": (
                        f"CPU at {current_pct:.1f}% for >{warn_win}min "
                        f"(threshold {warn_pct}%)"
                    ),
                })
        return alerts

    def _check_memory(self, current_pct: float) -> list[dict]:
        warn_pct = self._thresholds["memory_warning_pct"]
        if current_pct >= warn_pct:
            return [{
                "metric": "memory_pct",
                "level": "WARNING",
                "value": current_pct,
                "message": f"Memory at {current_pct:.1f}% (threshold {warn_pct}%)",
            }]
        return []

    def _check_disk(self, current_pct: float) -> list[dict]:
        crit_pct = self._thresholds["disk_critical_pct"]
        warn_pct = self._thresholds["disk_warning_pct"]
        if current_pct >= crit_pct:
            return [{
                "metric": "disk_pct",
                "level": "CRITICAL",
                "value": current_pct,
                "message": f"Disk at {current_pct:.1f}% (threshold {crit_pct}%)",
            }]
        if current_pct >= warn_pct:
            return [{
                "metric": "disk_pct",
                "level": "WARNING",
                "value": current_pct,
                "message": f"Disk at {current_pct:.1f}% (threshold {warn_pct}%)",
            }]
        return []

    # ------------------------------------------------------------------
    # Sustained-threshold check
    # ------------------------------------------------------------------

    def _sustained_above(self, metric: str, threshold: float, minutes: int) -> bool:
        """Return True if every reading in the last `minutes` exceeds threshold."""
        readings = self._db.get_recent_metrics(metric, minutes=minutes)
        if not readings:
            return False
        return all(r["value"] >= threshold for r in readings)

    # ------------------------------------------------------------------
    # Alert dispatch
    # ------------------------------------------------------------------

    def _dispatch_alert(self, alert: dict) -> None:
        level = alert["level"]
        if level == "CRITICAL":
            logger.error("resource_critical", **alert)
            # Voice alert to Dutch
            TaskQueue().push(
                agent="voice",
                payload={"action": "alert", "message": alert["message"], "priority": "urgent"},
                priority=1,
            )
            # Trigger auto-remediation
            TaskQueue().push(
                agent="scaling",
                payload={"action": "auto_remediate", "trigger": alert["metric"], "value": alert["value"]},
                priority=1,
            )
        else:
            logger.warning("resource_warning", **alert)
            # Add to daily brief
            TaskQueue().push(
                agent="reporting",
                payload={"action": "add_to_brief", "category": "resource_warning", "data": alert},
                priority=5,
            )
