"""
Strategy agent — high-level planning driven by intel, finance, and analytics signals.

Actions:
  analyze_growth_levers — assess what's driving/blocking growth; prioritized actions
  roadmap_priority      — rank backlog items using cross-agent signals
  competitor_signal     — receive competitor signal from research, store and assess
  quarterly_plan        — generate quarterly OKRs from current data
  okr_review            — review progress vs OKRs, flag off-track
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .db import StrategyDB
from .growth_analyzer import GrowthAnalyzer
from .quarterly_planner import QuarterlyPlanner
from .roadmap_prioritizer import RoadmapPrioritizer

logger = get_logger(__name__)


class StrategyAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = StrategyDB()
        self._growth = GrowthAnalyzer(self._db, cfg)
        self._roadmap = RoadmapPrioritizer(self._db, cfg)
        self._planner = QuarterlyPlanner(self._db, cfg)

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload
        product = p.get("product", "")

        dispatch = {
            "analyze_growth_levers": lambda: self._growth.run(product=_req(p, "product")),
            "roadmap_priority":      lambda: self._roadmap.run(
                                         product=_req(p, "product"),
                                         backlog=p.get("backlog", []),
                                     ),
            "competitor_signal":     lambda: self._ingest_signal(p, "competitor"),
            "market_signal":         lambda: self._ingest_signal(p, "market"),
            "market_shift":          lambda: self._ingest_signal(p, "market_shift"),
            "retention_signal":      lambda: self._ingest_signal(p, "retention"),
            "quarterly_plan":        lambda: self._planner.generate_plan(
                                         product=_req(p, "product"),
                                         quarter=_req(p, "quarter"),
                                     ),
            "okr_review":            lambda: self._planner.review_okrs(
                                         product=_req(p, "product"),
                                         quarter=_req(p, "quarter"),
                                     ),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown strategy action: {action}"},
            )

        logger.info("strategy_task_started", action=action, product=product, task_id=task.id)
        try:
            output = handler()
        except ValueError as exc:
            return TaskResult(task_id=task.id, success=False, output={"error": str(exc)})
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.list_signals(product="starpio", limit=1)
            return True
        except Exception:
            return False

    def _ingest_signal(self, p: dict[str, Any], signal_type: str) -> dict[str, Any]:
        product = p.get("product", "")
        summary = p.get("summary") or p.get("recommendation") or str(p.get("signals", ""))[:500]
        recommendation = p.get("recommended_response") or p.get("recommendation", "")
        source = p.get("source", "unknown")

        sig_id = self._db.save_signal(
            product=product,
            signal_type=signal_type,
            summary=summary[:1000],
            recommendation=recommendation[:500],
            source_agent=source,
        )
        return {"signal_id": sig_id, "signal_type": signal_type, "product": product}


def _req(payload: dict[str, Any], key: str) -> Any:
    val = payload.get(key)
    if not val:
        raise ValueError(f"Missing required field: {key}")
    return val


if __name__ == "__main__":
    config = AgentConfig.load("strategy")
    StrategyAgent("strategy", config).run()
