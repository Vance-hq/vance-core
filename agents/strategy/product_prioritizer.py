"""ProductPrioritizer — weekly product scoring and resource allocation ranking."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import StrategyDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are a strategic advisor to a SaaS founder. "
    "Score each product on a 0-10 scale across four dimensions: "
    "MRR growth rate, market opportunity, current momentum, and effort required. "
    "Produce a recommended resource allocation for this week. "
    "Output JSON array sorted highest score first:\n"
    "[{\"product\": str, \"score\": float, \"mrr_growth\": \"high|moderate|flat|declining\", "
    "\"momentum\": \"strong|moderate|weak\", \"effort\": \"low|medium|high\", "
    "\"focus\": str (one specific action to take this week)}]\n\n"
    "Be decisive. The highest-scored product should receive the most agent effort this week."
)


class ProductPrioritizer:

    def __init__(self, db: StrategyDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def prioritize(self, products: list[str]) -> dict[str, Any]:
        product_data: dict[str, list] = {}
        for product in products:
            signals = self._db.list_signals(product=product, actioned=False, limit=10)
            product_data[product] = signals

        context_lines: list[str] = []
        for product, signals in product_data.items():
            sig_summary = "; ".join(s["summary"][:100] for s in signals[:3]) or "No recent signals."
            context_lines.append(f"- {product}: {sig_summary}")

        prompt = (
            f"Products to rank:\n" + "\n".join(f"  - {p}" for p in products) + "\n\n"
            f"Recent context per product:\n" + "\n".join(context_lines)
        )

        try:
            resp = llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system=_SYSTEM,
                max_tokens=800,
            )
            raw = resp.content[0].text.strip()
            ranked = json.loads(raw)
            if not isinstance(ranked, list):
                raise ValueError("Expected JSON array")
            ranked.sort(key=lambda x: float(x.get("score", 0)), reverse=True)
        except Exception as exc:
            logger.warning("product_prioritizer_llm_failed", error=str(exc))
            ranked = [{"product": p, "score": 5.0, "mrr_growth": "unknown", "momentum": "unknown", "effort": "unknown", "focus": "Review signals"} for p in products]

        self._deliver_via_voice(ranked=ranked)

        logger.info("products_prioritized", products=len(ranked))
        return {"ranked_products": ranked, "products_evaluated": len(products)}

    def _deliver_via_voice(self, ranked: list[dict]) -> None:
        try:
            if not ranked:
                return
            top = ranked[0]
            rest = ", ".join(p["product"] for p in ranked[1:]) if len(ranked) > 1 else ""
            text = (
                f"Weekly product focus: {top['product']} is the top priority with a score of {top['score']:.1f}. "
                f"Recommended action: {top.get('focus', 'Review strategy')}."
            )
            if rest:
                text += f" Secondary products: {rest}."
            TaskQueue().push(
                "voice",
                {
                    "action": "speak",
                    "text": text,
                    "priority": "normal",
                    "source": "product_prioritizer",
                },
            )
        except Exception as exc:
            logger.warning("product_prioritizer_voice_failed", error=str(exc))
