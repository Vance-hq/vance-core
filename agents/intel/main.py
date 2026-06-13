"""
Intel agent — continuous market and competitor intelligence.

Actions:
  track_keyword           — monitor keyword search volume trends
  scan_industry_news      — scan news for product category, surface signals to strategy
  monitor_competitors_social — track competitor social activity
  detect_market_shift     — detect pricing/feature shifts across competitors
  digest_intel            — compile daily intel → reporting agent
"""

from __future__ import annotations

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .competitor_social_monitor import CompetitorSocialMonitor
from .db import IntelDB
from .intel_digest import IntelDigest
from .keyword_tracker import KeywordTracker
from .market_shift_detector import MarketShiftDetector
from .news_scanner import NewsScanner

logger = get_logger(__name__)


class IntelAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = IntelDB()
        self._keywords = KeywordTracker(self._db, cfg)
        self._news = NewsScanner(self._db, cfg)
        self._social = CompetitorSocialMonitor(self._db, cfg)
        self._shifts = MarketShiftDetector(self._db, cfg)
        self._digest = IntelDigest(self._db, cfg)

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload
        product = p.get("product", "")

        dispatch = {
            "track_keyword":             lambda: self._keywords.run(product=product),
            "scan_industry_news":        lambda: self._news.run(product=product),
            "monitor_competitors_social": lambda: self._social.run(product=product),
            "detect_market_shift":       lambda: self._shifts.run(product=product),
            "digest_intel":              lambda: self._digest.run(product=product),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown intel action: {action}"},
            )

        if action != "digest_intel" and not product:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": "product required"},
            )

        logger.info("intel_task_started", action=action, product=product, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.list_signals(min_relevance=0, limit=1)
            return True
        except Exception:
            return False


if __name__ == "__main__":
    config = AgentConfig.load("intel")
    IntelAgent("intel", config).run()
