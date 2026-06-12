"""
Research agent — continuous intelligence gathering.

Actions:
  competitor_monitor    — weekly competitor deep scan (pricing, features, jobs, reviews)
  market_signal_scan    — daily industry signal scan; relevance-scored, high signals to reporting
  customer_sentiment    — monthly batch analysis of support/NPS/review language
  feature_gap_analysis  — quarterly gap analysis vs competitors; top 3 to dev agent
  pricing_research      — quarterly pricing positioning research; report to strategy agent
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .competitor_monitor import CompetitorMonitor
from .customer_sentiment import CustomerSentiment
from .db import ResearchDB
from .feature_gap_analysis import FeatureGapAnalysis
from .market_signal_scan import MarketSignalScan
from .pricing_research import PricingResearch

logger = get_logger(__name__)


class ResearchAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = ResearchDB()
        self._competitor_monitor = CompetitorMonitor(self._db, cfg)
        self._signal_scan = MarketSignalScan(self._db, cfg)
        self._sentiment = CustomerSentiment(self._db, cfg)
        self._gap_analysis = FeatureGapAnalysis(self._db, cfg)
        self._pricing = PricingResearch(self._db, cfg)

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        product = p.get("product", "")
        if action in ("competitor_monitor", "market_signal_scan", "customer_sentiment",
                      "feature_gap_analysis", "pricing_research") and not product:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": "product required"},
            )

        dispatch = {
            "competitor_monitor":   lambda: self._competitor_monitor.run(product=product),
            "market_signal_scan":   lambda: self._signal_scan.run(product=product),
            "customer_sentiment":   lambda: self._sentiment.run(product=product),
            "feature_gap_analysis": lambda: self._gap_analysis.run(product=product),
            "pricing_research":     lambda: self._pricing.run(product=product),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown research action: {action}"},
            )

        logger.info("research_task_started", action=action, product=product, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.list_signals(product="starpio", min_relevance=0, limit=1)
            return True
        except Exception:
            return False


if __name__ == "__main__":
    config = AgentConfig.load("research")
    ResearchAgent("research", config).run()
