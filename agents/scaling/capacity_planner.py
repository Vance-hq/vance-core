"""Monthly capacity planning — trend analysis and hardware limit projection."""

from __future__ import annotations

import statistics
from datetime import datetime, timezone

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import ScalingDB

logger = get_logger(__name__)

_HORIZON_DAYS = 90  # how far ahead to project
_ANALYSIS_DAYS = 90  # how far back to look for trend data


class CapacityPlanner:
    """
    Analyse 90 days of resource metrics, compute growth rate via linear
    regression, project when each resource will hit its limit, and alert
    if the projected breach is within 90 days.
    """

    def __init__(self, cfg: dict, db: ScalingDB | None = None) -> None:
        self._cfg = cfg
        self._db = db or ScalingDB()
        self._limits = cfg.get("capacity_limits", {
            "cpu_pct": 90.0,
            "memory_pct": 90.0,
            "disk_pct": 85.0,
        })

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan(self) -> dict:
        """Run trend analysis across all tracked metrics. Return full report."""
        metrics = ["cpu_pct", "memory_pct", "disk_pct"]
        projections: dict[str, dict] = {}
        alerts: list[dict] = []

        for metric in metrics:
            history = self._db.get_metric_history(metric, days=_ANALYSIS_DAYS)
            if len(history) < 2:
                projections[metric] = {"status": "insufficient_data", "days_until_limit": None}
                continue

            growth_per_day, current = self._linear_regression(history)
            limit = self._limits.get(metric, 90.0)

            if growth_per_day <= 0:
                projections[metric] = {
                    "status": "stable_or_declining",
                    "current_pct": round(current, 2),
                    "growth_per_day": round(growth_per_day, 4),
                    "days_until_limit": None,
                }
                continue

            days_until_limit = (limit - current) / growth_per_day
            status = "ok"

            if days_until_limit <= _HORIZON_DAYS:
                status = "approaching_limit"
                alert = {
                    "metric": metric,
                    "current_pct": round(current, 2),
                    "limit_pct": limit,
                    "days_until_limit": round(days_until_limit, 1),
                    "growth_per_day": round(growth_per_day, 4),
                    "recommendation": self._recommendation(metric, days_until_limit),
                }
                alerts.append(alert)
                logger.warning("capacity_limit_approaching", **alert)

            projections[metric] = {
                "status": status,
                "current_pct": round(current, 2),
                "growth_per_day": round(growth_per_day, 4),
                "days_until_limit": round(days_until_limit, 1),
                "limit_pct": limit,
            }

        if alerts:
            self._notify(alerts)

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "analysis_days": _ANALYSIS_DAYS,
            "horizon_days": _HORIZON_DAYS,
            "projections": projections,
            "alerts": alerts,
        }

        self._db.insert_event(
            trigger="scheduled_plan",
            action_taken="capacity_analysis",
            outcome="success" if not alerts else "alerts_raised",
            metadata={"alert_count": len(alerts)},
        )

        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _linear_regression(self, history: list[dict]) -> tuple[float, float]:
        """
        Fit a simple linear regression: value = slope * day_index + intercept.
        Returns (slope_per_day, current_value_estimate).
        """
        n = len(history)
        xs = list(range(n))
        ys = [float(r["value"]) for r in history]

        mean_x = statistics.mean(xs)
        mean_y = statistics.mean(ys)

        numerator = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
        denominator = sum((xs[i] - mean_x) ** 2 for i in range(n))

        slope = numerator / denominator if denominator != 0 else 0.0
        current = ys[-1]  # most recent reading
        return slope, current

    def _recommendation(self, metric: str, days_until_limit: float) -> str:
        urgency = "immediately" if days_until_limit < 30 else "within the next month"
        recs = {
            "cpu_pct": (
                f"CPU approaching limit in ~{days_until_limit:.0f} days. "
                f"Plan new machine build {urgency}. "
                "Consider horizontal scaling or process optimisation."
            ),
            "memory_pct": (
                f"Memory approaching limit in ~{days_until_limit:.0f} days. "
                f"Add RAM or begin planning new machine build {urgency}."
            ),
            "disk_pct": (
                f"Disk approaching limit in ~{days_until_limit:.0f} days. "
                f"Expand storage or increase log rotation {urgency}."
            ),
        }
        return recs.get(metric, f"{metric} approaching limit in ~{days_until_limit:.0f} days.")

    def _notify(self, alerts: list[dict]) -> None:
        TaskQueue().push(
            agent="reporting",
            payload={"action": "capacity_plan_alert", "alerts": alerts},
            priority=2,
        )
