"""RoadmapPrioritizer — rank backlog items using signals from intel/research/analytics."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import StrategyDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are a product strategist ranking a backlog. Given items and supporting signals, "
    "rank the top 5 by business impact (revenue, retention, churn reduction). "
    "Output JSON only: [{\"item\": str, \"rank\": int, \"rationale\": str, \"estimated_impact\": \"high|medium|low\"}]"
)


class RoadmapPrioritizer:

    def __init__(self, db: StrategyDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str, backlog: list[str]) -> dict[str, Any]:
        if not backlog:
            return {"product": product, "ranked_items": [], "message": "no backlog items provided"}

        signals = self._db.list_signals(product=product, actioned=False, limit=10)
        signal_text = "\n".join(f"- {s['summary']}" for s in signals)

        prompt = (
            f"Product: {product}\n\n"
            f"Backlog items:\n" + "\n".join(f"- {item}" for item in backlog) +
            f"\n\nSupporting signals:\n{signal_text or 'none'}"
        )

        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM,
            max_tokens=600,
        )
        raw = resp.content[0].text.strip()
        try:
            ranked = json.loads(raw)
        except json.JSONDecodeError:
            match = __import__("re").search(r"\[.*\]", raw, __import__("re").DOTALL)
            ranked = json.loads(match.group(0)) if match else []

        logger.info("roadmap_prioritized", product=product, items=len(ranked))
        return {"product": product, "ranked_items": ranked}
