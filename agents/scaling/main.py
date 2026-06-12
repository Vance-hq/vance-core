"""Scaling agent — resource monitoring, alerting, remediation, and capacity planning."""

from __future__ import annotations

from agents._base import BaseAgent, AgentConfig
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .auto_remediation import AutoRemediation
from .capacity_planner import CapacityPlanner
from .db import ScalingDB
from .resource_collector import ResourceCollector
from .threshold_checker import ThresholdChecker

logger = get_logger(__name__)


class ScalingAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom or {}

        self._db = ScalingDB()
        self._collector = ResourceCollector(cfg, self._db)
        self._checker = ThresholdChecker(cfg, self._db)
        self._remediation = AutoRemediation(cfg, self._db)
        self._planner = CapacityPlanner(cfg, self._db)

        self._dispatch = {
            "resource_monitor": self._resource_monitor,
            "alert_threshold": self._alert_threshold,
            "auto_remediate": self._auto_remediate,
            "capacity_plan": self._capacity_plan,
        }

    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        logger.info("scaling_task_received", action=action, task_id=task.id)

        handler = self._dispatch.get(action)
        if not handler:
            return TaskResult(task_id=task.id, success=False, error=f"unknown action: {action}")

        try:
            output = handler(task.payload)
            return TaskResult(task_id=task.id, success=True, output=output)
        except Exception as exc:
            logger.error("scaling_task_failed", action=action, error=str(exc))
            return TaskResult(task_id=task.id, success=False, error=str(exc))

    def health_check(self) -> bool:
        try:
            self._db.get_recent_events(hours=1)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _resource_monitor(self, payload: dict) -> dict:
        return self._collector.collect()

    def _alert_threshold(self, payload: dict) -> dict:
        snapshot = self._collector.snapshot()
        alerts = self._checker.check(snapshot)
        return {"alerts": alerts, "snapshot": snapshot}

    def _auto_remediate(self, payload: dict) -> dict:
        trigger = payload.get("trigger", "")
        value = float(payload.get("value", 0.0))
        return self._remediation.remediate(trigger, value)

    def _capacity_plan(self, payload: dict) -> dict:
        return self._planner.plan()


if __name__ == "__main__":
    config = AgentConfig.load("scaling")
    ScalingAgent("scaling", config).run()
