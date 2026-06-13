"""
Strategy agent — highest-level agent: synthesizes signals, generates recommendations,
scores products, detects pivots, and evaluates opportunities.

Actions:
  synthesize_signals     — daily cross-product signal synthesis; identifies single most important pattern
  recommend_next_action  — 3 prioritized recommendations; auto-executes confidence > threshold
  product_prioritization — weekly product scoring and resource allocation ranking
  pivot_detection        — detects failing product strategy; surfaces diagnosis to Dutch before action
  opportunity_evaluate   — scores opportunities; auto-initiates research on score >= 8

Legacy actions (preserved for backward compat):
  analyze_growth_levers  — assess growth levers and blockers
  roadmap_priority       — rank backlog items using signals
  competitor_signal      — ingest competitor signal
  market_signal          — ingest market signal
  market_shift           — ingest market shift signal
  retention_signal       — ingest retention signal
  quarterly_plan         — generate quarterly OKRs
  okr_review             — review OKR progress
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .action_recommender import ActionRecommender
from .db import StrategyDB
from .growth_analyzer import GrowthAnalyzer
from .opportunity_evaluator import OpportunityEvaluator
from .pivot_detector import PivotDetector
from .product_prioritizer import ProductPrioritizer
from .quarterly_planner import QuarterlyPlanner
from .roadmap_prioritizer import RoadmapPrioritizer
from .signal_synthesizer import SignalSynthesizer

logger = get_logger(__name__)


class StrategyAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = StrategyDB()
        # Legacy modules
        self._growth = GrowthAnalyzer(self._db, cfg)
        self._roadmap = RoadmapPrioritizer(self._db, cfg)
        self._planner = QuarterlyPlanner(self._db, cfg)
        # New modules
        self._synthesizer = SignalSynthesizer(self._db, cfg)
        self._recommender = ActionRecommender(self._db, cfg)
        self._prioritizer = ProductPrioritizer(self._db, cfg)
        self._pivot_detector = PivotDetector(self._db, cfg)
        self._opp_evaluator = OpportunityEvaluator(self._db, cfg)

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload
        products = self.config.custom.get("products", ["starpio", "oneserv", "localoutrank"])

        dispatch = {
            # New high-level actions
            "synthesize_signals":     lambda: self._synthesizer.synthesize(products=products),
            "recommend_next_action":  lambda: self._recommender.recommend(products=products),
            "product_prioritization": lambda: self._prioritizer.prioritize(products=products),
            "pivot_detection":        lambda: self._pivot_detection(p),
            "opportunity_evaluate":   lambda: self._opportunity_evaluate(p),
            # Legacy actions
            "analyze_growth_levers":  lambda: self._growth.run(product=_req(p, "product")),
            "roadmap_priority":       lambda: self._roadmap.run(
                                          product=_req(p, "product"),
                                          backlog=p.get("backlog", []),
                                      ),
            "competitor_signal":      lambda: self._ingest_signal(p, "competitor"),
            "market_signal":          lambda: self._ingest_signal(p, "market"),
            "market_shift":           lambda: self._ingest_signal(p, "market_shift"),
            "retention_signal":       lambda: self._ingest_signal(p, "retention"),
            "quarterly_plan":         lambda: self._planner.generate_plan(
                                          product=_req(p, "product"),
                                          quarter=_req(p, "quarter"),
                                      ),
            "okr_review":             lambda: self._planner.review_okrs(
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

        logger.info("strategy_task_started", action=action, task_id=task.id)
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

    def _pivot_detection(self, p: dict[str, Any]) -> dict[str, Any]:
        product = p.get("product")
        if not product:
            raise ValueError("Missing required field: product")
        return self._pivot_detector.detect(product=product)

    def _opportunity_evaluate(self, p: dict[str, Any]) -> dict[str, Any]:
        opportunity = p.get("opportunity")
        if not opportunity:
            raise ValueError("Missing required field: opportunity")
        return self._opp_evaluator.evaluate(opportunity=opportunity)

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
