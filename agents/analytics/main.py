"""
Analytics Agent — behavioral and usage intelligence across all products.

Actions:
  usage_snapshot        — daily per-product metrics from Umami + Supabase
  funnel_analysis       — visit→signup→activated→paid→retained funnel with WoW regression check
  cohort_analysis       — monthly cohort retention at 30/60/90 days; feeds strategy agent
  feature_usage         — weekly feature adoption; surfaces unused → onboarding, gaps → research
  engagement_score      — per-user score + tier; AT_RISK → sales, DORMANT → onboarding
  cross_product_report  — unified daily view across all products → reporting agent
  ab_test_tracker       — central A/B registry; auto-concludes at p<0.05, notifies owning agent
  on_demand_query       — LLM-driven ad-hoc analytics for voice delivery
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .ab_test_manager import ABTestManager
from .cohort_tracker import CohortTracker
from .cross_product_reporter import CrossProductReporter
from .db import AnalyticsDB
from .engagement_scorer import EngagementScorer
from .feature_tracker import FeatureTracker
from .funnel_analyzer import FunnelAnalyzer
from .query_answerer import QueryAnswerer
from .usage_collector import UsageCollector

logger = get_logger(__name__)


class AnalyticsAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = AnalyticsDB()
        self._usage = UsageCollector(self._db, cfg)
        self._funnel = FunnelAnalyzer(self._db, cfg)
        self._cohort = CohortTracker(self._db, cfg)
        self._feature = FeatureTracker(self._db, cfg)
        self._engagement = EngagementScorer(self._db, cfg)
        self._cross = CrossProductReporter(self._db, cfg)
        self._ab = ABTestManager(self._db, cfg)
        self._query = QueryAnswerer(cfg)

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "usage_snapshot":       lambda: self._usage.run(
                                        product=_require(p, "product"),
                                        date_str=p.get("date"),
                                    ),
            "funnel_analysis":      lambda: self._funnel.run(
                                        product=_require(p, "product"),
                                        date_str=p.get("date"),
                                    ),
            "cohort_analysis":      lambda: self._cohort.run(
                                        product=_require(p, "product"),
                                        cohort_month=p.get("cohort_month"),
                                    ),
            "feature_usage":        lambda: self._feature.run(
                                        product=_require(p, "product"),
                                        week=p.get("week"),
                                    ),
            "engagement_score":     lambda: self._engagement.run(
                                        product=_require(p, "product"),
                                    ),
            "cross_product_report": lambda: self._cross.run(),
            "ab_test_tracker":      lambda: self._handle_ab_test(p),
            "on_demand_query":      lambda: self._query.run(
                                        question=_require(p, "question"),
                                    ),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown analytics action: {action}"},
            )

        logger.info("analytics_task_started", action=action, task_id=task.id)
        try:
            output = handler()
        except ValueError as exc:
            return TaskResult(task_id=task.id, success=False, output={"error": str(exc)})
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.get_recent_usage(product="starpio", days=1)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _handle_ab_test(self, p: dict[str, Any]) -> dict[str, Any]:
        sub = p.get("sub_action", "update")
        if sub == "register":
            return self._ab.register_test(
                agent=_require(p, "agent"),
                product=_require(p, "product"),
                test_name=_require(p, "test_name"),
                variant_a=_require(p, "variant_a"),
                variant_b=_require(p, "variant_b"),
                metric=_require(p, "metric"),
            )
        if sub == "check_all":
            return self._ab.check_all_running()
        return self._ab.update_test(
            agent=_require(p, "agent"),
            product=_require(p, "product"),
            test_name=_require(p, "test_name"),
            sample_a=int(p.get("sample_size_a", 0)),
            sample_b=int(p.get("sample_size_b", 0)),
            conversions_a=int(p.get("conversions_a", 0)),
            conversions_b=int(p.get("conversions_b", 0)),
        )


def _require(payload: dict[str, Any], key: str) -> Any:
    val = payload.get(key)
    if not val:
        raise ValueError(f"Missing required field: {key}")
    return val


if __name__ == "__main__":
    config = AgentConfig.load("analytics")
    AnalyticsAgent("analytics", config).run()
