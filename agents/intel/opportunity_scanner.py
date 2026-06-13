"""Opportunity scanner — ProductHunt, API integrations, affiliate partners; LLM-scored."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

logger = get_logger(__name__)

HIGH_SCORE_THRESHOLD = 7


def _fetch_product_hunt(api_key: str, days_back: int = 30) -> list[dict[str, Any]]:
    """Fetch recent ProductHunt launches via SerpAPI."""
    import httpx

    try:
        resp = httpx.get(
            "https://serpapi.com/search",
            params={"q": "site:producthunt.com new product launch", "tbm": "nws", "num": 10, "api_key": api_key},
            timeout=15,
        )
        data = resp.json()
        items = []
        for r in data.get("news_results", data.get("organic_results", [])):
            items.append({
                "type": "product_hunt",
                "description": r.get("title", ""),
                "source_url": r.get("link", ""),
                "snippet": r.get("snippet", ""),
            })
        return items
    except Exception as exc:
        logger.warning("product_hunt_fetch_failed", error=str(exc))
        return []


def _fetch_api_integrations(keywords: list[str], api_key: str) -> list[dict[str, Any]]:
    """Search for new API integrations relevant to our products."""
    import httpx

    items = []
    for kw in keywords[:3]:  # limit queries
        try:
            resp = httpx.get(
                "https://serpapi.com/search",
                params={"q": f"{kw} API integration 2026", "num": 5, "api_key": api_key},
                timeout=15,
            )
            for r in resp.json().get("organic_results", [])[:2]:
                items.append({
                    "type": "api_integration",
                    "description": r.get("title", ""),
                    "source_url": r.get("link", ""),
                    "snippet": r.get("snippet", ""),
                })
        except Exception as exc:
            logger.warning("api_integration_fetch_failed", keyword=kw, error=str(exc))
    return items


def _fetch_affiliate_partners(keywords: list[str], api_key: str) -> list[dict[str, Any]]:
    """Search for potential affiliate/referral partners."""
    import httpx

    items = []
    for kw in keywords[:2]:
        try:
            resp = httpx.get(
                "https://serpapi.com/search",
                params={"q": f"{kw} affiliate program partnership", "num": 5, "api_key": api_key},
                timeout=15,
            )
            for r in resp.json().get("organic_results", [])[:2]:
                items.append({
                    "type": "affiliate",
                    "description": r.get("title", ""),
                    "source_url": r.get("link", ""),
                    "snippet": r.get("snippet", ""),
                })
        except Exception as exc:
            logger.warning("affiliate_fetch_failed", keyword=kw, error=str(exc))
    return items


class OpportunityScanner:

    def __init__(self, db: Any, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self) -> dict[str, Any]:
        api_key = self._cfg.get("serp_api_key", "")
        opportunity_keywords = self._cfg.get("opportunity_keywords", [])

        opportunities: list[dict[str, Any]] = []
        opportunities.extend(_fetch_product_hunt(api_key))
        opportunities.extend(_fetch_api_integrations(opportunity_keywords, api_key))
        opportunities.extend(_fetch_affiliate_partners(opportunity_keywords, api_key))

        high_score_count = 0
        saved_ids: list[str] = []

        for opp in opportunities:
            if not opp.get("description"):
                continue
            scoring = self._score_opportunity(opp)
            opp_id = self._db.save_opportunity(
                type_=opp["type"],
                description=opp["description"],
                source_url=opp.get("source_url", ""),
                score=scoring["score"],
                relevance=scoring["relevance"],
                effort=scoring["effort"],
                potential_impact=scoring["potential_impact"],
            )
            saved_ids.append(opp_id)

            if scoring["score"] >= HIGH_SCORE_THRESHOLD:
                self._route_to_strategy(opp, scoring)
                high_score_count += 1

        return {
            "opportunities_found": len(opportunities),
            "opportunities_saved": len(saved_ids),
            "high_score_count": high_score_count,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _score_opportunity(self, opp: dict[str, Any]) -> dict[str, Any]:
        context = f"Type: {opp['type']}\nDescription: {opp['description']}\nSnippet: {opp.get('snippet', '')}"
        try:
            resp = llm.complete(
                messages=[{"role": "user", "content": context}],
                system=(
                    "You are a business development analyst. Score this opportunity for a B2B SaaS. "
                    'Return JSON with keys: "score" (1-10 overall), "relevance" (1-10), '
                    '"effort" ("low"/"medium"/"high"), "potential_impact" ("low"/"medium"/"high"), '
                    '"rationale" (one sentence).'
                ),
                max_tokens=200,
            )
            raw = resp.content[0].text
            # strip markdown fences if present
            raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            data = json.loads(raw)
            return {
                "score": int(data.get("score", 5)),
                "relevance": int(data.get("relevance", 5)),
                "effort": str(data.get("effort", "medium")),
                "potential_impact": str(data.get("potential_impact", "medium")),
                "rationale": str(data.get("rationale", "")),
            }
        except Exception as exc:
            logger.warning("opportunity_scoring_failed", error=str(exc))
            return {"score": 5, "relevance": 5, "effort": "medium", "potential_impact": "medium", "rationale": ""}

    def _route_to_strategy(self, opp: dict[str, Any], scoring: dict[str, Any]) -> None:
        try:
            TaskQueue().push(
                "strategy",
                {
                    "action": "market_signal",
                    "signal_type": "opportunity",
                    "summary": opp["description"],
                    "source_url": opp.get("source_url", ""),
                    "score": scoring["score"],
                    "effort": scoring["effort"],
                    "potential_impact": scoring["potential_impact"],
                },
            )
        except Exception as exc:
            logger.warning("opportunity_strategy_dispatch_failed", error=str(exc))
