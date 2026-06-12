"""
Content calendar planner — 30-day plan stored in Postgres, individual tasks enqueued.

Pull in:
  - Upcoming product launches (from config or DB)
  - Seasonal trends (web search)
  - Competitor content gaps (web search)

Produces: structured JSON calendar → Postgres content_calendar → enqueue per entry.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from shared.llm.client import llm, web_search
from shared.logger import get_logger

from .db import ContentDB

logger = get_logger(__name__)

_CALENDAR_SYSTEM = """You are a content strategist. Plan 30 days of content for a SaaS product.

Rules:
- Mix platforms: LinkedIn, Twitter, blog, Facebook, newsletter (at least one of each per week).
- Every entry must have a concrete, specific topic — not "tips for X" but "how to fix X problem".
- Space out types: don't schedule two blog posts in the same week.
- Use the competitor gap and trend research to choose topics that aren't already saturated.

Output a JSON array of exactly 30 objects with these fields:
  date         (YYYY-MM-DD)
  platform     (linkedin | twitter | blog | facebook | newsletter)
  type         (social_post | blog_post | newsletter)
  topic        (specific topic string)
  status       (pending)

Return only valid JSON — no explanation, no markdown fences.
"""

_COMPETITOR_PRODUCTS: dict[str, list[str]] = {
    "starpio": ["grade.us", "birdeye", "podium"],
    "oneserv": ["jobber", "housecall pro", "servicetitan"],
    "localoutrank": ["brightlocal", "whitespark", "semrush local"],
    "trusted_plumbing": [],
}

_JSON_RE = re.compile(r"\[.*\]", re.DOTALL)


def enqueue_content_task(entry_id: str, entry: dict[str, Any]) -> None:
    """Enqueue a Celery task for a calendar entry on its scheduled date."""
    from agents.content.tasks import schedule_content_entry
    try:
        scheduled_date = entry.get("date") or str(date.today())
        eta = date.fromisoformat(scheduled_date)
        from datetime import datetime, timezone
        eta_dt = datetime(eta.year, eta.month, eta.day, 9, 0, tzinfo=timezone.utc)
        schedule_content_entry.apply_async(
            kwargs={"entry_id": entry_id, "entry": entry},
            eta=eta_dt,
        )
    except Exception as exc:
        logger.warning("enqueue_content_task_failed", entry_id=entry_id, error=str(exc))


class CalendarPlanner:

    def __init__(self, db: ContentDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def plan(self, product: str) -> dict[str, Any]:
        # 1. Gather context
        trends = self._search_trends(product)
        competitor_gaps = self._search_competitor_gaps(product)

        # 2. LLM generates 30-entry calendar
        raw = self._generate(product, trends, competitor_gaps)
        entries = self._parse(raw)

        # 3. Save to DB and enqueue tasks
        saved: list[dict[str, Any]] = []
        start_date = date.today()
        for i, entry in enumerate(entries):
            # Use LLM-provided date or auto-assign sequentially
            entry_date_str = entry.get("date")
            try:
                entry_date = date.fromisoformat(entry_date_str) if entry_date_str else start_date + timedelta(days=i)
            except ValueError:
                entry_date = start_date + timedelta(days=i)

            entry_id = self._db.save_calendar_entry(
                product=product,
                scheduled_date=entry_date,
                platform=entry.get("platform", "linkedin"),
                content_type=entry.get("type", "social_post"),
                topic=entry.get("topic", ""),
                status="pending",
            )

            full_entry = {
                "date": str(entry_date),
                "platform": entry.get("platform"),
                "type": entry.get("type"),
                "topic": entry.get("topic"),
                "status": "pending",
                "entry_id": entry_id,
                "product": product,
            }
            saved.append(full_entry)
            enqueue_content_task(entry_id, full_entry)

        logger.info("content_calendar_planned", product=product, entries=len(saved))
        return {"total_entries": len(saved), "calendar": saved}

    # ------------------------------------------------------------------

    def _search_trends(self, product: str) -> list[dict[str, str]]:
        queries = [f"{product} industry trends {date.today().year}"]
        results: list[dict[str, str]] = []
        for q in queries:
            try:
                results.extend(web_search(q, num_results=5))
            except Exception as exc:
                logger.warning("calendar_trend_search_failed", error=str(exc))
        return results[:5]

    def _search_competitor_gaps(self, product: str) -> list[dict[str, str]]:
        competitors = _COMPETITOR_PRODUCTS.get(product, [])
        results: list[dict[str, str]] = []
        for comp in competitors[:2]:
            try:
                results.extend(web_search(f"{comp} blog content topics", num_results=5))
            except Exception as exc:
                logger.warning("calendar_competitor_search_failed", competitor=comp, error=str(exc))
        return results[:10]

    def _generate(
        self,
        product: str,
        trends: list[dict[str, str]],
        gaps: list[dict[str, str]],
    ) -> str:
        trend_text = "\n".join(r.get("title", "") + ": " + r.get("content", "")[:80] for r in trends[:5])
        gap_text = "\n".join(r.get("title", "") for r in gaps[:8])
        start = date.today()

        prompt = (
            f"Product: {product}\n"
            f"Calendar starts: {start}\n\n"
            f"Trending topics in the industry:\n{trend_text or 'No data.'}\n\n"
            f"Competitor content topics (gaps to fill):\n{gap_text or 'No data.'}\n\n"
            "Plan 30 days of content."
        )
        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_CALENDAR_SYSTEM,
            max_tokens=2500,
            metadata={"caller": "content.calendar_planner"},
        ).content[0].text.strip()

    def _parse(self, raw: str) -> list[dict[str, Any]]:
        try:
            match = _JSON_RE.search(raw)
            data = json.loads(match.group() if match else raw)
            if isinstance(data, list):
                return data[:30]
        except (json.JSONDecodeError, AttributeError):
            logger.warning("calendar_json_parse_failed", raw_preview=raw[:120])
        return []
