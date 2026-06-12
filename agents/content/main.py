"""
Content agent — produces and publishes written content across all products.

Actions:
  write_blog_post      — research, draft, SEO optimize, publish
  write_social_post    — LinkedIn / Twitter / Facebook (platform-specific format)
  write_newsletter     — weekly email newsletter, broadcast send
  update_landing_page  — 3 A/B section variants committed to repo
  content_calendar     — 30-day plan → Postgres → enqueue tasks
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .blog_writer import BlogWriter
from .calendar_planner import CalendarPlanner
from .db import ContentDB
from .landing_writer import LandingWriter
from .newsletter_writer import NewsletterWriter
from .social_writer import SocialWriter

logger = get_logger(__name__)


class ContentAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = ContentDB()
        self._blog = BlogWriter(self._db, cfg)
        self._social = SocialWriter(self._db, cfg)
        self._newsletter = NewsletterWriter(self._db, cfg)
        self._landing = LandingWriter(self._db, cfg)
        self._calendar = CalendarPlanner(self._db, cfg)

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "write_blog_post":     lambda: self._handle_blog(p),
            "write_social_post":   lambda: self._handle_social(p),
            "write_newsletter":    lambda: self._handle_newsletter(p),
            "update_landing_page": lambda: self._handle_landing(p),
            "content_calendar":    lambda: self._handle_calendar(p),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown content action: {action}"},
            )

        logger.info("content_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.get_recent_pieces(product="starpio", limit=1)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # write_blog_post
    # ------------------------------------------------------------------

    def _handle_blog(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          product          (str) — starpio | oneserv | localoutrank | trusted_plumbing
          topic            (str) — keyword or topic to write about
          target_audience  (str) — who the post is for
          word_count       (int) — target length

        Optional:
          publish (bool) — push live via WordPress or markdown commit
        """
        product = p.get("product")
        topic = p.get("topic")
        target_audience = p.get("target_audience", "")
        word_count = int(p.get("word_count", 800))
        publish = bool(p.get("publish", False))

        if not product or not topic:
            return {"error": "product and topic required"}

        return self._blog.write(
            product=product,
            topic=topic,
            target_audience=target_audience,
            word_count=word_count,
            publish=publish,
        )

    # ------------------------------------------------------------------
    # write_social_post
    # ------------------------------------------------------------------

    def _handle_social(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          product  (str) — product identifier
          platform (str) — linkedin | twitter | facebook
          topic    (str) — what to write about

        Optional:
          schedule (bool) — push to Buffer
        """
        product = p.get("product")
        platform = p.get("platform")
        topic = p.get("topic", "")
        schedule = bool(p.get("schedule", False))

        if not product or not platform:
            return {"error": "product and platform required"}

        return self._social.write(
            product=product,
            platform=platform,
            topic=topic,
            schedule=schedule,
        )

    # ------------------------------------------------------------------
    # write_newsletter
    # ------------------------------------------------------------------

    def _handle_newsletter(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          product (str)

        Optional:
          send (bool) — broadcast via Resend
        """
        product = p.get("product")
        send = bool(p.get("send", False))

        if not product:
            return {"error": "product required"}

        return self._newsletter.write(product=product, send=send)

    # ------------------------------------------------------------------
    # update_landing_page
    # ------------------------------------------------------------------

    def _handle_landing(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          product            (str) — product identifier
          section            (str) — hero | benefits | pricing | faq | cta
          performance_signal (str) — low conversion | high bounce | heatmap signal
        """
        product = p.get("product")
        section = p.get("section")
        signal = p.get("performance_signal", "")

        if not product or not section:
            return {"error": "product and section required"}

        return self._landing.write(
            product=product,
            section=section,
            performance_signal=signal,
        )

    # ------------------------------------------------------------------
    # content_calendar
    # ------------------------------------------------------------------

    def _handle_calendar(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          product (str)
        """
        product = p.get("product")

        if not product:
            return {"error": "product required"}

        return self._calendar.plan(product=product)


if __name__ == "__main__":
    config = AgentConfig.load("content")
    ContentAgent("content", config).run()
