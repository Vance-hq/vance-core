"""
PricingResearch — quarterly competitor pricing analysis.

Pulls pricing from competitor websites. LLM produces recommendation.
Does NOT change pricing — delivers report to strategy agent.
"""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import ResearchDB

logger = get_logger(__name__)

_PRICING_SYSTEM = (
    "You are a pricing strategist. Given competitor pricing data, "
    "recommend optimal pricing positioning. "
    "Reply with JSON only: "
    "{\"competitor_pricing\": {competitor: {tier: price}}, "
    "\"recommendation\": str, \"rationale\": str}. "
    "Be specific and actionable in the recommendation."
)


def web_search(query: str, num_results: int = 5) -> list[dict[str, Any]]:
    from shared.search import search as _search
    try:
        return _search(query, num_results=num_results)
    except Exception as exc:
        logger.warning("web_search_failed", query=query, error=str(exc))
        return []


def enqueue_strategy_report(
    product: str,
    recommendation: str,
    rationale: str,
    competitor_pricing: dict,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="strategy",
            payload={
                "action": "pricing_report",
                "product": product,
                "recommendation": recommendation,
                "rationale": rationale,
                "competitor_pricing": competitor_pricing,
                "source": "research",
            },
        )
    except Exception as exc:
        logger.warning("enqueue_strategy_pricing_failed", product=product, error=str(exc))


class PricingResearch:

    def __init__(self, db: ResearchDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        competitors: list[str] = prod_cfg.get("competitors", [])
        product_name = prod_cfg.get("name", product)

        pricing_snippets: list[str] = []
        for competitor in competitors:
            hits = web_search(f"{competitor} pricing plans cost per month", num_results=5)
            for hit in hits:
                snippet = hit.get("snippet", "")
                title = hit.get("title", "")
                if snippet or title:
                    pricing_snippets.append(f"{competitor}: {title} — {snippet}")

        prompt = (
            f"Product: {product_name}\n"
            f"Competitors: {', '.join(competitors)}\n\n"
            f"Pricing evidence found:\n"
            + "\n".join(pricing_snippets[:20] or ["(no pricing data found)"])
        )

        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_PRICING_SYSTEM,
            max_tokens=1024,
        )
        raw = resp.content[0].text.strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {
                "competitor_pricing": {},
                "recommendation": raw[:300],
                "rationale": "",
            }

        competitor_pricing = parsed.get("competitor_pricing", {})
        recommendation = parsed.get("recommendation", "")
        rationale = parsed.get("rationale", "")

        enqueue_strategy_report(
            product=product,
            recommendation=recommendation,
            rationale=rationale,
            competitor_pricing=competitor_pricing,
        )

        logger.info("pricing_research_complete", product=product, competitors=len(competitors))
        return {
            "product": product,
            "competitors_researched": len(competitors),
            "competitor_pricing": competitor_pricing,
            "recommendation": recommendation,
            "rationale": rationale,
        }
