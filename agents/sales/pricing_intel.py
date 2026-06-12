"""
Pricing intel — weekly competitor pricing monitor.

Uses web_search() to pull current pricing data for each competitor.
LLM compares against current product pricing.
If a significant change is detected, enqueues a strategy agent alert.
"""

from __future__ import annotations

from typing import Any

from shared.llm.client import llm, web_search
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import SalesDB

logger = get_logger(__name__)

# Competitors to monitor per product
_COMPETITORS: dict[str, list[str]] = {
    "starpio": [
        "OpenTable restaurant pricing plans",
        "Resy business pricing",
        "Eat App restaurant reservation pricing",
    ],
    "oneserv": [
        "ServiceTitan pricing plans 2024",
        "Jobber pricing plans 2024",
        "Housecall Pro pricing",
    ],
    "localoutrank": [
        "Birdeye pricing plans",
        "BrightLocal pricing",
        "Podium pricing plans 2024",
    ],
}

_INTEL_SYSTEM = """You are a competitive pricing analyst.

Given web search snippets about competitor pricing, produce a structured analysis:
1. What pricing tiers/plans each competitor offers (name + price if found)
2. Any notable pricing changes vs typical market rates
3. Whether any competitor appears significantly cheaper or more expensive than typical SaaS rates
4. A confidence score (low/medium/high) based on how fresh and complete the data is

Output as plain text, 3-5 sentences. Flag "SIGNIFICANT_CHANGE" at the start if you detect
a change that warrants immediate review (>20% price movement, new free tier, major restructuring).
"""

_SIGNIFICANCE_MARKER = "SIGNIFICANT_CHANGE"


class PricingIntel:

    def __init__(self, db: SalesDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._queue = TaskQueue()

    def run(self, products: list[str] | None = None) -> dict[str, Any]:
        targets = products or list(_COMPETITORS.keys())
        results: dict[str, Any] = {}
        alerts_sent = 0

        for product in targets:
            competitors = _COMPETITORS.get(product, [])
            if not competitors:
                continue

            snippets: list[str] = []
            for query in competitors:
                try:
                    found = web_search(query, num_results=3)
                    snippets.extend(found)
                except Exception as exc:
                    logger.warning("pricing_search_failed", query=query, error=str(exc))

            if not snippets:
                results[product] = {"analysis": "no_data", "significant": False}
                continue

            raw = "\n\n".join(snippets[:9])
            analysis = llm.complete(
                messages=[{"role": "user", "content": f"Product: {product}\n\nSearch results:\n{raw}"}],
                system=_INTEL_SYSTEM,
                max_tokens=300,
                metadata={"caller": "sales.pricing_intel"},
            ).content[0].text.strip()

            significant = analysis.startswith(_SIGNIFICANCE_MARKER)
            results[product] = {"analysis": analysis, "significant": significant}

            if significant:
                self._alert_strategy(product, analysis)
                alerts_sent += 1
                logger.info("pricing_intel_alert_queued", product=product)

            self._db.log_action(
                product=product,
                action_type="pricing_intel_alert" if significant else "pricing_intel_alert",
                meta={"significant": significant, "analysis_preview": analysis[:200]},
            )

        return {"products_checked": len(targets), "alerts_sent": alerts_sent, "results": results}

    def _alert_strategy(self, product: str, analysis: str) -> None:
        self._queue.push(
            agent="strategy",
            payload={
                "action": "pricing_change_alert",
                "product": product,
                "analysis": analysis,
                "source": "pricing_intel",
            },
        )
