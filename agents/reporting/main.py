"""
Reporting agent — cross-agent digest and alert broadcast.

Actions:
  add_to_brief      — queued by other agents to add items to today's digest
  daily_brief       — compile + send daily digest from accumulated brief_items
  weekly_digest     — compile + send weekly performance digest
  alert_broadcast   — immediate broadcast of critical alerts
  export_report     — export structured brief data for a date range
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .alert_broadcaster import AlertBroadcaster
from .brief_compiler import BriefCompiler
from .db import ReportingDB

logger = get_logger(__name__)


class ReportingAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = ReportingDB()
        self._compiler = BriefCompiler(self._db, cfg)
        self._broadcaster = AlertBroadcaster(cfg)

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "add_to_brief":    lambda: self._add_to_brief(p),
            "daily_brief":     lambda: self._compiler.compile_daily(p.get("date")),
            "weekly_digest":   lambda: self._weekly_digest(p),
            "alert_broadcast": lambda: self._broadcaster.broadcast(
                title=p.get("title", "Alert"),
                message=p.get("message", ""),
                severity=p.get("severity", "medium"),
                source=p.get("source", "unknown"),
            ),
            "export_report":   lambda: self._export(p),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown reporting action: {action}"},
            )

        logger.info("reporting_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.get_brief_items()
            return True
        except Exception:
            return False

    def _add_to_brief(self, p: dict[str, Any]) -> dict[str, Any]:
        section = p.get("section", "general")
        data = p.get("data", {})
        source = p.get("source", "unknown")
        item_id = self._db.add_brief_item(section=section, data=data, source=source)
        return {"item_id": item_id, "section": section}

    def _weekly_digest(self, p: dict[str, Any]) -> dict[str, Any]:
        to_date = p.get("to_date") or date.today().isoformat()
        from_date = p.get("from_date") or (date.fromisoformat(to_date) - timedelta(days=6)).isoformat()
        return self._compiler.compile_weekly(from_date=from_date, to_date=to_date)

    def _export(self, p: dict[str, Any]) -> dict[str, Any]:
        from_date = p.get("from_date", date.today().isoformat())
        to_date = p.get("to_date", date.today().isoformat())
        items = self._db.get_brief_items_range(from_date=from_date, to_date=to_date)
        return {"from_date": from_date, "to_date": to_date, "items": items, "count": len(items)}


if __name__ == "__main__":
    config = AgentConfig.load("reporting")
    ReportingAgent("reporting", config).run()
