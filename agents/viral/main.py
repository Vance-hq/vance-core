"""
Viral agent — trend monitoring, viral content creation, hook generation,
winner remixing, and competitor gap analysis.

Actions:
  trend_monitor          — scan sources, score trends, auto-enqueue viral pieces
  create_viral_piece     — fast-path content timed to a live trend
  hook_generator         — 10 ranked hook variants with rubric scores
  remix_winner           — weekly: take top pieces, remix for other platforms
  competitor_content_gap — monthly: find topics competitors cover poorly
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .db import ViralDB
from .gap_finder import GapFinder
from .hook_generator import HookGenerator
from .piece_creator import PieceCreator
from .remix_engine import RemixEngine
from .trend_scanner import TrendScanner

logger = get_logger(__name__)


class ViralAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = ViralDB()
        self._scanner = TrendScanner(self._db, cfg)
        self._creator = PieceCreator(self._db, cfg)
        self._hooks = HookGenerator(cfg)
        self._remixer = RemixEngine(self._db, cfg)
        self._gap_finder = GapFinder(cfg)

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "trend_monitor":          lambda: self._handle_trend_monitor(p),
            "create_viral_piece":     lambda: self._handle_create_piece(p),
            "hook_generator":         lambda: self._handle_hooks(p),
            "remix_winner":           lambda: self._handle_remix(p),
            "competitor_content_gap": lambda: self._handle_gaps(p),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown viral action: {action}"},
            )

        logger.info("viral_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.get_recent_trends(hours=1)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # trend_monitor
    # ------------------------------------------------------------------

    def _handle_trend_monitor(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Optional:
          product (str) — scan a single product; omit to scan all
        """
        product = p.get("product")
        if product:
            trends = self._scanner.scan(product)
            return {"product": product, "trends_found": len(trends), "trends": trends}
        return self._scanner.scan_all()

    # ------------------------------------------------------------------
    # create_viral_piece
    # ------------------------------------------------------------------

    def _handle_create_piece(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          trend_topic              (str)
          product                  (str)
          platform                 (str) — twitter | tiktok | linkedin | facebook
          opportunity_window_hours (int)

        Optional:
          trend_id (str) — link to trends_detected row
        """
        trend_topic = p.get("trend_topic", "")
        product = p.get("product", "")
        platform = p.get("platform", "twitter")
        window = int(p.get("opportunity_window_hours", 4))
        trend_id = p.get("trend_id", "")

        if not trend_topic or not product:
            return {"error": "trend_topic and product required"}

        return self._creator.create(
            trend_id=trend_id,
            trend_topic=trend_topic,
            product=product,
            platform=platform,
            opportunity_window_hours=window,
        )

    # ------------------------------------------------------------------
    # hook_generator
    # ------------------------------------------------------------------

    def _handle_hooks(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          topic    (str)
          platform (str)
          tone     (str) — controversial | educational | personal_story | data_driven
        """
        topic = p.get("topic", "")
        platform = p.get("platform", "twitter")
        tone = p.get("tone", "educational")

        if not topic:
            return {"error": "topic required"}

        return self._hooks.generate(topic=topic, platform=platform, tone=tone)

    # ------------------------------------------------------------------
    # remix_winner
    # ------------------------------------------------------------------

    def _handle_remix(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          product (str)
        """
        product = p.get("product", "")
        if not product:
            return {"error": "product required"}

        return self._remixer.remix(product=product)

    # ------------------------------------------------------------------
    # competitor_content_gap
    # ------------------------------------------------------------------

    def _handle_gaps(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          product (str)
        """
        product = p.get("product", "")
        if not product:
            return {"error": "product required"}

        return self._gap_finder.find_gaps(product=product)


if __name__ == "__main__":
    config = AgentConfig.load("viral")
    ViralAgent("viral", config).run()
