"""
Launch agent — product launch and major release orchestration.

Actions:
  plan_launch          — build timestamped launch plan for every relevant agent
  execute_launch       — poll and dispatch due tasks; alert on critical failures
  product_hunt_launch  — full PH copy generation + social scheduling + Dutch notification
  launch_debrief       — T+7 metrics pull, LLM narrative, voice report delivery
"""

from __future__ import annotations

from datetime import date
from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .db import LaunchDB
from .debrief import LaunchDebrief
from .executor import LaunchExecutor
from .planner import LaunchPlanner
from .product_hunt import ProductHuntLaunch

logger = get_logger(__name__)

_VALID_LAUNCH_TYPES = {"new_product", "major_feature", "price_change", "rebrand"}


class LaunchAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = LaunchDB()
        self._planner = LaunchPlanner(self._db, cfg)
        self._executor = LaunchExecutor(self._db, cfg)
        self._product_hunt = ProductHuntLaunch(self._db, cfg)
        self._debrief = LaunchDebrief(self._db, cfg)

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "plan_launch":         lambda: self._handle_plan(p),
            "execute_launch":      lambda: self._executor.run(),
            "product_hunt_launch": lambda: self._handle_ph(p),
            "launch_debrief":      lambda: self._handle_debrief(p),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown launch action: {action}"},
            )

        logger.info("launch_task_started", action=action, task_id=task.id)
        output = handler()
        if isinstance(output, dict) and "error" in output:
            return TaskResult(task_id=task.id, success=False, output=output)
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.list_pending_tasks()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # plan_launch
    # ------------------------------------------------------------------

    def _handle_plan(self, p: dict[str, Any]) -> dict[str, Any]:
        product = p.get("product", "")
        launch_type = p.get("launch_type", "")
        launch_date_str = p.get("launch_date", "")

        if not product:
            return {"error": "product required"}
        if not launch_date_str:
            return {"error": "launch_date required (YYYY-MM-DD)"}
        if launch_type not in _VALID_LAUNCH_TYPES:
            launch_type = "major_feature"

        try:
            launch_date = date.fromisoformat(launch_date_str)
        except ValueError:
            return {"error": f"launch_date must be YYYY-MM-DD, got: {launch_date_str}"}

        return self._planner.plan(
            product=product,
            launch_type=launch_type,
            launch_date=launch_date,
        )

    # ------------------------------------------------------------------
    # product_hunt_launch
    # ------------------------------------------------------------------

    def _handle_ph(self, p: dict[str, Any]) -> dict[str, Any]:
        product = p.get("product", "")
        launch_date_str = p.get("launch_date", "")

        if not product:
            return {"error": "product required"}

        try:
            launch_date = date.fromisoformat(launch_date_str) if launch_date_str else date.today()
        except ValueError:
            launch_date = date.today()

        return self._product_hunt.orchestrate(product=product, launch_date=launch_date)

    # ------------------------------------------------------------------
    # launch_debrief
    # ------------------------------------------------------------------

    def _handle_debrief(self, p: dict[str, Any]) -> dict[str, Any]:
        plan_id = p.get("plan_id", "")
        product = p.get("product", "")
        if not all([plan_id, product]):
            return {"error": "plan_id and product required"}
        return self._debrief.run(plan_id=plan_id, product=product)


if __name__ == "__main__":
    config = AgentConfig.load("launch")
    LaunchAgent("launch", config).run()
