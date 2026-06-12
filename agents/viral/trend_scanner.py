"""
Trend scanner — multi-source trend detection with LLM relevance/velocity scoring.

Sources:
  - Web search (Google Trends proxy via SearXNG/DDG)
  - X/Twitter trending via Apify scraper
  - Reddit relevant subreddits
  - TikTok trending topics

Run every 3 hours via Celery beat.
Auto-enqueues create_viral_piece when relevance >= threshold AND velocity == "rising".
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from shared.llm.client import llm, web_search
from shared.logger import get_logger

from .db import ViralDB

logger = get_logger(__name__)

_SCORE_SYSTEM = """You are a trend analyst for a SaaS company targeting small businesses.

Given a list of trending topics and a product context, score each trend.

Output a JSON array. Each object must have:
  topic           (string  — the trend topic, cleaned up)
  relevance       (int     — 0-10, how relevant to the product and its customers)
  velocity        (string  — "rising" | "peak" | "declining")
  window_hours    (int     — estimated hours before trend fades)

Relevance guide:
  9-10: directly about the product category or a problem it solves
  7-8:  adjacent industry topic, can be tied to product value
  4-6:  loosely related, stretch to make relevant
  1-3:  not relevant

Return valid JSON array only — no explanation, no markdown.
"""

_PRODUCT_CONTEXT: dict[str, str] = {
    "starpio": "review management for restaurants and local businesses — Google, Yelp, Facebook reviews",
    "oneserv": "field service management for trades contractors — HVAC, plumbing, electrical",
    "localoutrank": "local SEO — Google Business Profile, rank tracking, citation management",
    "trusted_plumbing": "local plumbing company — residential and commercial plumbing service",
}

_REDDIT_SUBS: dict[str, list[str]] = {
    "starpio": ["r/restaurantowners", "r/smallbusiness", "r/entrepreneur"],
    "oneserv": ["r/HVAC", "r/plumbing", "r/Contractors"],
    "localoutrank": ["r/SEO", "r/smallbusiness", "r/GoogleBusiness"],
    "trusted_plumbing": ["r/HomeImprovement", "r/Plumbing"],
}

_JSON_RE = re.compile(r"\[.*\]", re.DOTALL)


def enqueue_viral_piece(
    trend_id: str,
    trend_topic: str,
    product: str,
    platform: str,
    opportunity_window_hours: int,
) -> None:
    """Enqueue a create_viral_piece Celery task immediately."""
    from agents.viral.tasks import create_viral_piece_task
    try:
        create_viral_piece_task.delay(
            trend_id=trend_id,
            trend_topic=trend_topic,
            product=product,
            platform=platform,
            opportunity_window_hours=opportunity_window_hours,
        )
    except Exception as exc:
        logger.warning("enqueue_viral_piece_failed", trend_id=trend_id, error=str(exc))


class TrendScanner:

    def __init__(self, db: ViralDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._threshold = int(cfg.get("relevance_threshold", 7))

    def scan_all(self) -> dict[str, Any]:
        products = self._cfg.get("products", [])
        all_trends: list[dict[str, Any]] = []
        for product in products:
            trends = self.scan(product)
            all_trends.extend(trends)
        return {"scanned": len(products), "trends_found": len(all_trends)}

    def scan(self, product: str) -> list[dict[str, Any]]:
        """Scan all sources for this product, score, save, and auto-enqueue."""
        raw_topics = self._collect_topics(product)
        if not raw_topics:
            logger.info("trend_scan_no_topics", product=product)
            return []

        scored = self._score_trends(product, raw_topics)
        saved: list[dict[str, Any]] = []

        for item in scored:
            topic = item.get("topic", "")
            relevance = float(item.get("relevance", 0))
            velocity = item.get("velocity", "peak")
            window = int(item.get("window_hours", 4))

            # Determine best platform for this trend
            platform = self._pick_platform(product, topic)

            trend_id = self._db.save_trend(
                trend_topic=topic,
                platform=platform,
                relevance_score=relevance,
                velocity=velocity,
                opportunity_window_hours=window,
                product=product,
            )

            entry = {
                "trend_id": trend_id,
                "topic": topic,
                "relevance": relevance,
                "velocity": velocity,
                "window_hours": window,
                "platform": platform,
            }
            saved.append(entry)

            if relevance >= self._threshold and velocity == "rising":
                enqueue_viral_piece(
                    trend_id=trend_id,
                    trend_topic=topic,
                    product=product,
                    platform=platform,
                    opportunity_window_hours=window,
                )
                self._db.mark_trend_acted_on(trend_id)
                logger.info("viral_piece_enqueued", topic=topic, product=product, relevance=relevance)

        return saved

    # ------------------------------------------------------------------

    def _collect_topics(self, product: str) -> list[str]:
        topics: list[str] = []
        context = _PRODUCT_CONTEXT.get(product, product)

        # Web search for trending topics
        try:
            results = web_search(f"trending {context} topics news today", num_results=8)
            topics.extend(r["title"] for r in results if r.get("title"))
        except Exception as exc:
            logger.warning("trend_web_search_failed", product=product, error=str(exc))

        # Reddit search
        subs = _REDDIT_SUBS.get(product, [])
        for sub in subs[:2]:
            try:
                results = web_search(f"site:reddit.com {sub} hot posts today", num_results=3)
                topics.extend(r["title"] for r in results if r.get("title"))
            except Exception as exc:
                logger.warning("trend_reddit_failed", sub=sub, error=str(exc))

        # Apify Twitter scraper (if token configured)
        apify_token = self._cfg.get("apify_api_token", "")
        if apify_token:
            try:
                twitter_topics = self._fetch_twitter_trends(apify_token, context)
                topics.extend(twitter_topics)
            except Exception as exc:
                logger.warning("trend_twitter_failed", error=str(exc))

        return list(dict.fromkeys(topics))[:20]  # dedupe, cap at 20

    def _fetch_twitter_trends(self, token: str, context: str) -> list[str]:
        resp = httpx.post(
            "https://api.apify.com/v2/acts/quacker~twitter-search-scraper/run-sync-get-dataset-items",
            headers={"Authorization": f"Bearer {token}"},
            json={"searchTerms": [context], "maxItems": 10, "sort": "Latest"},
            timeout=30,
        )
        if resp.status_code == 200:
            items = resp.json()
            return [item.get("text", "")[:120] for item in items[:10] if item.get("text")]
        return []

    def _score_trends(
        self, product: str, topics: list[str]
    ) -> list[dict[str, Any]]:
        context = _PRODUCT_CONTEXT.get(product, product)
        topic_list = "\n".join(f"- {t}" for t in topics[:20])
        prompt = (
            f"Product: {product}\n"
            f"Context: {context}\n\n"
            f"Trending topics:\n{topic_list}\n\n"
            "Score each trend."
        )
        raw = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_SCORE_SYSTEM,
            max_tokens=1000,
            metadata={"caller": "viral.trend_scanner"},
        ).content[0].text.strip()

        try:
            match = _JSON_RE.search(raw)
            data = json.loads(match.group() if match else raw)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, AttributeError):
            logger.warning("trend_score_parse_failed", raw_preview=raw[:100])
            return []

    def _pick_platform(self, product: str, topic: str) -> str:
        topic_lower = topic.lower()
        if any(w in topic_lower for w in ("video", "tiktok", "reel", "short")):
            return "tiktok"
        if any(w in topic_lower for w in ("linkedin", "b2b", "enterprise", "saas")):
            return "linkedin"
        return "twitter"
