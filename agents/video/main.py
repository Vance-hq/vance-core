"""
Video agent — script generation, shorts creation, title optimization, and performance tracking.

Actions:
  create_script     — LLM video script for given topic/persona
  create_shorts     — extract 3 short-form clip outlines from a long script
  optimize_title    — A/B title alternatives for YouTube SEO
  track_performance — pull video analytics from YouTube, surface insights
  list_scripts      — list generated scripts per product
"""

from __future__ import annotations

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .db import VideoDB
from .performance_tracker import PerformanceTracker
from .script_creator import ScriptCreator

logger = get_logger(__name__)


class VideoAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = VideoDB()
        self._creator = ScriptCreator(self._db, cfg)
        self._perf = PerformanceTracker(self._db, cfg)

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "create_script":    lambda: self._creator.create_script(
                                    product=p.get("product", ""),
                                    topic=_req(p, "topic"),
                                    persona=p.get("persona", "small business owner"),
                                    tone=p.get("tone", "conversational"),
                                    fmt=p.get("format", "long"),
                                ),
            "create_shorts":    lambda: {"clips": self._creator.create_shorts(script=_req(p, "script"))},
            "optimize_title":   lambda: {"alternatives": self._creator.optimize_title(
                                    topic=_req(p, "topic"),
                                    current_title=_req(p, "current_title"),
                                )},
            "track_performance": lambda: self._perf.run(
                                    video_ids=p.get("video_ids", []),
                                    platform=p.get("platform", "youtube"),
                                ),
            "list_scripts":     lambda: {
                                    "scripts": self._db.list_scripts(
                                        product=p.get("product", ""),
                                        status=p.get("status"),
                                    )
                                },
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown video action: {action}"},
            )

        logger.info("video_task_started", action=action, task_id=task.id)
        try:
            output = handler()
        except ValueError as exc:
            return TaskResult(task_id=task.id, success=False, output={"error": str(exc)})
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.list_scripts(product="starpio", limit=1)
            return True
        except Exception:
            return False


def _req(payload: dict, key: str):
    val = payload.get(key)
    if not val:
        raise ValueError(f"Missing required field: {key}")
    return val


if __name__ == "__main__":
    config = AgentConfig.load("video")
    VideoAgent("video", config).run()
