"""
Competitor content gap finder — monthly task.

Process:
  1. Scrape top competitor blog titles via web search (no headless browser needed)
  2. LLM identifies: topics covered poorly, unanswered audience questions
  3. Returns 10 gap topics ranked by estimated search volume
  4. Enqueues top 3 to content agent as write_blog_post tasks
"""

from __future__ import annotations

import json
import re
from typing import Any

from shared.llm.client import llm, web_search
from shared.logger import get_logger

logger = get_logger(__name__)

_GAP_SYSTEM = """You are a content strategist doing a competitive gap analysis.

Given a list of competitor blog post titles and a product description, identify content gaps.

A gap is a topic where:
  - Competitors cover it poorly or superficially
  - Their audience asks questions that go unanswered
  - The topic is underserved relative to search demand

Output a JSON array of exactly 10 objects, sorted by estimated_search_volume descending:
  topic                   (string  — specific topic title, not generic)
  estimated_search_volume (int     — monthly searches, rough estimate)
  reason                  (string  — one sentence: why this is a gap)

Return only valid JSON — no explanation, no markdown.
"""

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

_PRODUCT_CONTEXT: dict[str, str] = {
    "starpio": "review management SaaS for restaurants and local businesses",
    "oneserv": "field service management SaaS for trades contractors",
    "localoutrank": "local SEO SaaS for Google Business Profile and rank tracking",
    "trusted_plumbing": "local plumbing service company",
}


def enqueue_blog_post(product: str, topic: str) -> None:
    """Enqueue a write_blog_post task to the content agent."""
    from agents.content.tasks import schedule_content_entry
    import uuid
    from datetime import date, datetime, timedelta, timezone
    try:
        eta_date = date.today() + timedelta(days=3)
        eta_dt = datetime(eta_date.year, eta_date.month, eta_date.day, 9, 0, tzinfo=timezone.utc)
        schedule_content_entry.apply_async(
            kwargs={
                "entry_id": str(uuid.uuid4()),
                "entry": {
                    "product": product,
                    "platform": "blog",
                    "type": "blog_post",
                    "topic": topic,
                    "date": str(eta_date),
                },
            },
            eta=eta_dt,
        )
    except Exception as exc:
        logger.warning("gap_enqueue_blog_failed", product=product, topic=topic, error=str(exc))


class GapFinder:

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg

    def find_gaps(self, product: str) -> dict[str, Any]:
        competitor_content = self._scrape_competitors(product)
        gaps = self._analyze_gaps(product, competitor_content)

        # Sort by search volume descending
        gaps.sort(key=lambda g: g.get("estimated_search_volume", 0), reverse=True)
        gaps = gaps[:10]

        # Enqueue top 3 to content agent
        for gap in gaps[:3]:
            enqueue_blog_post(product=product, topic=gap["topic"])

        logger.info("gap_analysis_complete", product=product, gaps=len(gaps))
        return {"product": product, "gaps": gaps}

    # ------------------------------------------------------------------

    def _scrape_competitors(self, product: str) -> list[str]:
        competitor_blogs = self._cfg.get("competitor_blogs", {}).get(product, [])
        titles: list[str] = []

        for blog_url in competitor_blogs:
            try:
                results = web_search(f"site:{blog_url}", num_results=10)
                titles.extend(r["title"] for r in results if r.get("title"))
            except Exception as exc:
                logger.warning("gap_scrape_failed", blog=blog_url, error=str(exc))

        # Also search for general competitor blog topics without site: filter
        context = _PRODUCT_CONTEXT.get(product, product)
        try:
            results = web_search(f"{context} blog posts topics", num_results=10)
            titles.extend(r["title"] for r in results if r.get("title"))
        except Exception as exc:
            logger.warning("gap_general_search_failed", error=str(exc))

        return list(dict.fromkeys(titles))[:50]

    def _analyze_gaps(self, product: str, competitor_titles: list[str]) -> list[dict[str, Any]]:
        context = _PRODUCT_CONTEXT.get(product, product)
        title_list = "\n".join(f"- {t}" for t in competitor_titles[:40])

        prompt = (
            f"Product: {product}\n"
            f"Context: {context}\n\n"
            f"Competitor blog post titles:\n{title_list or 'No data found.'}\n\n"
            "Identify 10 content gaps."
        )
        raw = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_GAP_SYSTEM,
            max_tokens=1000,
            metadata={"caller": "viral.gap_finder"},
        ).content[0].text.strip()

        try:
            match = _JSON_ARRAY_RE.search(raw)
            data = json.loads(match.group() if match else raw)
            if isinstance(data, list):
                return data[:10]
        except (json.JSONDecodeError, AttributeError):
            logger.warning("gap_parse_failed", raw_preview=raw[:100])

        return []
