"""
Intel agent — market intelligence + deep competitor monitoring.

Original actions (5):
  track_keyword           — monitor keyword search volume trends
  scan_industry_news      — scan news for product category, surface signals to strategy
  monitor_competitors_social — track competitor social activity
  detect_market_shift     — detect pricing/feature shifts across competitors
  digest_intel            — compile daily intel → reporting agent

New actions (4):
  competitor_activity_watch — Playwright screenshot diff, blog/LinkedIn/jobs/G2 monitoring
  press_monitoring          — SerpAPI news for product/founder/competitor names
  community_listen          — Reddit + Facebook (Apify) + LinkedIn community scanning
  opportunity_scan          — Monthly ProductHunt/API/affiliate scan, LLM scored → strategy
"""

from __future__ import annotations

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .community_listener import CommunityListener
from .competitor_social_monitor import CompetitorSocialMonitor
from .competitor_watcher import CompetitorWatcher
from .db import IntelDB
from .intel_digest import IntelDigest
from .keyword_tracker import KeywordTracker
from .market_shift_detector import MarketShiftDetector
from .news_scanner import NewsScanner
from .opportunity_scanner import OpportunityScanner
from .press_monitor import PressMonitor

logger = get_logger(__name__)

_ACTIONS_REQUIRING_PRODUCT = {
    "track_keyword",
    "scan_industry_news",
    "monitor_competitors_social",
    "detect_market_shift",
    "competitor_activity_watch",
    "press_monitoring",
    "community_listen",
}


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
        self._watcher = CompetitorWatcher(self._db, cfg)
        self._press = PressMonitor(self._db, cfg)
        self._community = CommunityListener(self._db, cfg)
        self._opportunities = OpportunityScanner(self._db, cfg)

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload
        product = p.get("product", "")

        dispatch = {
            # original 5
            "track_keyword":              lambda: self._keywords.run(product=product),
            "scan_industry_news":         lambda: self._news.run(product=product),
            "monitor_competitors_social": lambda: self._social.run(product=product),
            "detect_market_shift":        lambda: self._shifts.run(product=product),
            "digest_intel":               lambda: self._digest.run(product=product),
            # new 4
            "competitor_activity_watch":  lambda: self._watcher.run(product=product),
            "press_monitoring":           lambda: self._press.run(product=product),
            "community_listen":           lambda: self._community.run(product=product),
            "opportunity_scan":           lambda: self._opportunities.run(),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown intel action: {action}"},
            )

        if action in _ACTIONS_REQUIRING_PRODUCT and not product:
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
