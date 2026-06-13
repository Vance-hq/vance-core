"""QuarterlyPlanner — generate quarterly OKRs from current data."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import StrategyDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are a strategic planning expert. Given product signals and business context, "
    "generate 3 quarterly OKRs (Objective + 2-3 Key Results each). "
    "Be specific — key results must be measurable with numbers. "
    "Output JSON only: [{\"objective\": str, \"key_results\": [str]}]"
)

_OKR_REVIEW_SYSTEM = (
    "You are a strategic planning expert reviewing OKR progress. "
    "Given OKRs and current signals, identify which are on-track, at-risk, or off-track. "
    "Output JSON: [{\"objective\": str, \"status\": \"on_track|at_risk|off_track\", \"note\": str}]"
)


class QuarterlyPlanner:

    def __init__(self, db: StrategyDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def generate_plan(self, product: str, quarter: str) -> dict[str, Any]:
        signals = self._db.list_signals(product=product, actioned=False, limit=15)
        signal_text = "\n".join(f"- [{s['signal_type']}] {s['summary']}" for s in signals)

        prompt = f"Product: {product}\nQuarter: {quarter}\n\nSignals:\n{signal_text or 'No signals available.'}"
        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM,
            max_tokens=800,
        )
        raw = resp.content[0].text.strip()
        try:
            okrs = json.loads(raw)
        except json.JSONDecodeError:
            okrs = []

        growth_levers = [s["summary"] for s in signals[:3]]
        plan_id = self._db.upsert_plan(
            product=product,
            quarter=quarter,
            okrs=okrs,
            growth_levers=growth_levers,
            status="draft",
        )

        logger.info("quarterly_plan_generated", product=product, quarter=quarter, okrs=len(okrs))
        return {"product": product, "quarter": quarter, "plan_id": plan_id, "okrs": okrs}

    def review_okrs(self, product: str, quarter: str) -> dict[str, Any]:
        plan = self._db.get_plan(product=product, quarter=quarter)
        if not plan:
            return {"error": f"No plan found for {product} {quarter}"}

        signals = self._db.list_signals(product=product, actioned=False, limit=10)
        signal_text = "\n".join(f"- {s['summary']}" for s in signals)
        okrs_text = json.dumps(plan.get("okrs", []), indent=2)

        prompt = f"OKRs:\n{okrs_text}\n\nCurrent signals:\n{signal_text}"
        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_OKR_REVIEW_SYSTEM,
            max_tokens=600,
        )
        raw = resp.content[0].text.strip()
        try:
            review = json.loads(raw)
        except json.JSONDecodeError:
            review = []

        off_track = [r for r in review if r.get("status") == "off_track"]
        logger.info("okr_review_complete", product=product, quarter=quarter, off_track=len(off_track))
        return {"product": product, "quarter": quarter, "review": review, "off_track_count": len(off_track)}
