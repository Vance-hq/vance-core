"""Community listener — Reddit, Facebook (Apify), LinkedIn monitoring."""

from __future__ import annotations

import json
from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

logger = get_logger(__name__)

SUBREDDITS = ["msp", "smallbusiness", "Plumbing", "SaaS", "Entrepreneur"]

_RECOMMENDATION_PHRASES = [
    "recommend", "suggestions", "looking for", "best tool", "anyone use",
    "what do you use", "alternatives to", "looking for software", "need a",
]
_COMPLAINT_PHRASES = [
    "hate", "terrible", "worst", "switched from", "left", "canceled",
    "disappointed", "frustrating", "overpriced", "not worth",
]


def _fetch_reddit_posts(subreddit: str, limit: int = 25) -> list[dict[str, Any]]:
    """Fetch newest posts from a subreddit via public JSON API."""
    import httpx

    try:
        resp = httpx.get(
            f"https://www.reddit.com/r/{subreddit}/new.json",
            params={"limit": limit},
            headers={"User-Agent": "VanceIntel/1.0"},
            timeout=15,
        )
        children = resp.json().get("data", {}).get("children", [])
        return [c["data"] for c in children]
    except Exception as exc:
        logger.warning("reddit_fetch_failed", subreddit=subreddit, error=str(exc))
        return []


def _fetch_apify_facebook(actor_run_id: str, apify_token: str) -> list[dict[str, Any]]:
    """Fetch results from a completed Apify actor run."""
    import httpx

    try:
        resp = httpx.get(
            f"https://api.apify.com/v2/actor-runs/{actor_run_id}/dataset/items",
            params={"token": apify_token, "limit": 50},
            timeout=20,
        )
        return resp.json() if isinstance(resp.json(), list) else []
    except Exception as exc:
        logger.warning("apify_fetch_failed", run_id=actor_run_id, error=str(exc))
        return []


class CommunityListener:

    def __init__(self, db: Any, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        competitors = prod_cfg.get("competitors", [])
        keywords = prod_cfg.get("keywords", [])
        subreddits = self._cfg.get("subreddits", SUBREDDITS)

        recommendation_requests = 0
        competitor_complaints = 0

        # --- Reddit ---
        for sub in subreddits:
            posts = _fetch_reddit_posts(sub)
            for post in posts:
                signal = self._classify_post(post.get("title", ""), post.get("selftext", ""), competitors, keywords)
                if signal is None:
                    continue
                url = f"https://reddit.com{post.get('permalink', '')}"
                mention_id = self._db.save_community_signal(
                    platform="reddit",
                    post_url=url,
                    signal_type=signal,
                    summary=post.get("title", "")[:200],
                    relevance_score=self._relevance_score(post, keywords),
                    subreddit=sub,
                )
                if mention_id is None:
                    continue  # duplicate
                if signal == "recommendation_request":
                    self._route_to_outreach(post, url, product)
                    recommendation_requests += 1
                elif signal == "competitor_complaint":
                    self._route_to_content(post, url, product)
                    competitor_complaints += 1

        # --- Facebook via Apify ---
        apify_run_id = self._cfg.get("apify_facebook_run_id", "")
        apify_token = self._cfg.get("apify_api_token", "")
        if apify_run_id and apify_token:
            fb_posts = _fetch_apify_facebook(apify_run_id, apify_token)
            for post in fb_posts:
                text = post.get("text", "")
                url = post.get("url", "")
                signal = self._classify_post(text, "", competitors, keywords)
                if signal is None or not url:
                    continue
                mention_id = self._db.save_community_signal(
                    platform="facebook",
                    post_url=url,
                    signal_type=signal,
                    summary=text[:200],
                    relevance_score=5,
                )
                if mention_id is None:
                    continue
                if signal == "recommendation_request":
                    self._route_to_outreach({"title": text}, url, product)
                    recommendation_requests += 1
                elif signal == "competitor_complaint":
                    self._route_to_content({"title": text}, url, product)
                    competitor_complaints += 1

        return {
            "product": product,
            "subreddits_checked": len(subreddits),
            "recommendation_requests": recommendation_requests,
            "competitor_complaints": competitor_complaints,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _classify_post(
        self, title: str, body: str, competitors: list[str], keywords: list[str]
    ) -> str | None:
        text = (title + " " + body).lower()
        has_product_context = any(k.lower() in text for k in keywords) or any(c.lower() in text for c in competitors)
        if not has_product_context and not any(phrase in text for phrase in _RECOMMENDATION_PHRASES + _COMPLAINT_PHRASES):
            return None

        if any(phrase in text for phrase in _COMPLAINT_PHRASES) and any(c.lower() in text for c in competitors):
            return "competitor_complaint"
        if any(phrase in text for phrase in _RECOMMENDATION_PHRASES):
            return "recommendation_request"
        return None

    def _relevance_score(self, post: dict[str, Any], keywords: list[str]) -> int:
        text = (post.get("title", "") + " " + post.get("selftext", "")).lower()
        matches = sum(1 for k in keywords if k.lower() in text)
        score = min(10, 4 + matches * 2)
        upvotes = post.get("score", 0)
        if upvotes > 100:
            score = min(10, score + 2)
        return score

    def _route_to_outreach(self, post: dict[str, Any], url: str, product: str) -> None:
        try:
            TaskQueue().push(
                "outreach",
                {
                    "action": "community_lead",
                    "product": product,
                    "post_title": post.get("title", "")[:200],
                    "post_url": url,
                    "context": "recommendation_request",
                },
            )
        except Exception as exc:
            logger.warning("community_outreach_dispatch_failed", error=str(exc))

    def _route_to_content(self, post: dict[str, Any], url: str, product: str) -> None:
        try:
            TaskQueue().push(
                "content",
                {
                    "action": "competitor_complaint_signal",
                    "product": product,
                    "post_title": post.get("title", "")[:200],
                    "post_url": url,
                    "context": "competitor_complaint",
                },
            )
        except Exception as exc:
            logger.warning("community_content_dispatch_failed", error=str(exc))
