"""GrowthAnalyzer — assess growth levers and blockers, return prioritized actions."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import StrategyDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are a SaaS growth strategist. Given metrics, signals, and context, "
    "identify the top 3 growth levers (what's working, should be doubled down) "
    "and top 3 blockers (what's preventing growth). For each, provide a specific action. "
    "Output JSON only: "
    "{\"levers\": [{\"name\": str, \"impact\": \"high|medium\", \"action\": str}], "
    "\"blockers\": [{\"name\": str, \"severity\": \"high|medium\", \"action\": str}], "
    "\"priority_action\": str}"
)


class GrowthAnalyzer:

    def __init__(self, db: StrategyDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        signals = self._db.list_signals(product=product, actioned=False, limit=10)
        context = self._build_context(product, signals)

        resp = llm.complete(
            messages=[{"role": "user", "content": context}],
            system=_SYSTEM,
            max_tokens=800,
        )
        raw = resp.content[0].text.strip()
        try:
            analysis = json.loads(raw)
        except json.JSONDecodeError:
            analysis = {"levers": [], "blockers": [], "priority_action": raw[:300]}

        logger.info("growth_analysis_complete", product=product, levers=len(analysis.get("levers", [])))
        return {"product": product, **analysis}

    def _build_context(self, product: str, signals: list[dict]) -> str:
        signal_text = "\n".join(
            f"- [{s['signal_type']}] {s['summary']} (recommended: {s['recommendation']})"
            for s in signals
        )
        return f"Product: {product}\n\nRecent signals:\n{signal_text or 'No signals yet.'}"
