"""Research agent — stub."""

from __future__ import annotations

from agents._base import BaseAgent, AgentConfig
from shared.logger import get_logger
from shared.types import Task, TaskResult

logger = get_logger(__name__)


class ResearchAgent(BaseAgent):

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        logger.info("research_task_received", action=action, task_id=task.id)
        return TaskResult(task_id=task.id, success=True, output={"status": "stub", "action": action})

    def health_check(self) -> bool:
        return True


if __name__ == "__main__":
    config = AgentConfig.load("research")
    ResearchAgent("research", config).run()
