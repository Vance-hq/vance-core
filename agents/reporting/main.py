"""
Reporting agent — cross-agent digest, briefing, and alert delivery.

Actions:
  add_to_brief      — queued by other agents to add items to today's digest
  daily_brief       — compile + deliver morning briefing (voice + email)
  weekly_summary    — week-over-week trend analysis + Markdown report + voice
  alert_deliver     — immediate delivery of priority alerts (voice + Slack + email)
  on_demand_report  — generate focused report from a voice intent
  weekly_digest     — (legacy) compile + send weekly digest via email
  alert_broadcast   — (legacy) broadcast alert via Slack + email
  export_report     — (legacy) export raw brief items for a date range
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .alert_broadcaster import AlertBroadcaster
from .alert_deliverer import AlertDeliverer
from .brief_compiler import BriefCompiler
from .daily_briefer import DailyBriefer
from .db import ReportingDB
from .on_demand_reporter import OnDemandReporter
from .weekly_summarizer import WeeklySummarizer

logger = get_logger(__name__)


class ReportingAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = ReportingDB()
        self._compiler = BriefCompiler(self._db, cfg)
        self._broadcaster = AlertBroadcaster(cfg)
        self._daily_briefer = DailyBriefer(self._db, cfg)
        self._weekly_summarizer = WeeklySummarizer(self._db, cfg)
        self._alert_deliverer = AlertDeliverer(self._db, cfg)
        self._on_demand_reporter = OnDemandReporter(self._db, cfg)

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            # Current actions
            "add_to_brief":     lambda: self._add_to_brief(p),
            "daily_brief":      lambda: self._daily_briefer.compile(p.get("date")),
            "weekly_summary":   lambda: self._weekly_summary(p),
            "alert_deliver":    lambda: self._alert_deliverer.deliver(
                source_agent=p.get("source_agent", "unknown"),
                alert_type=p.get("alert_type", "general"),
                message=p.get("message", ""),
                severity=p.get("severity", "high"),
            ),
            "on_demand_report": lambda: self._on_demand_reporter.generate(
                intent=p.get("intent", ""),
                product=p.get("product"),
                save=p.get("save", False),
            ),
            # Legacy actions (backward compat)
            "weekly_digest":    lambda: self._weekly_digest(p),
            "alert_broadcast":  lambda: self._broadcaster.broadcast(
                title=p.get("title", "Alert"),
                message=p.get("message", ""),
                severity=p.get("severity", "medium"),
                source=p.get("source", "unknown"),
            ),
            "export_report":    lambda: self._export(p),
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

    def _weekly_summary(self, p: dict[str, Any]) -> dict[str, Any]:
        to_date = p.get("to_date") or date.today().isoformat()
        from_date = p.get("from_date") or (date.fromisoformat(to_date) - timedelta(days=6)).isoformat()
        return self._weekly_summarizer.compile(from_date=from_date, to_date=to_date)

    # ------------------------------------------------------------------
    # Legacy handlers
    # ------------------------------------------------------------------

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
