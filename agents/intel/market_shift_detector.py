"""MarketShiftDetector — detect pricing/feature shifts across competitors."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import IntelDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are a market analyst. Given search results about competitor pricing and features, "
    "detect any significant market shifts: pricing drops/increases, new features, "
    "new entrants, or product discontinuations. "
    "Output JSON: {\"shifts_detected\": bool, \"shifts\": [{\"type\": str, \"description\": str, \"impact\": \"high|medium|low\"}]}"
)


class MarketShiftDetector:

    def __init__(self, db: IntelDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        competitors = self._cfg.get("products", {}).get(product, {}).get("competitors", [])
        all_shifts: list[dict] = []

        for comp in competitors:
            shifts = self._detect_shifts(product=product, competitor=comp)
            all_shifts.extend(shifts)

        if all_shifts:
            self._notify_strategy(product=product, shifts=all_shifts)

        logger.info("market_shift_check_complete", product=product, shifts=len(all_shifts))
        return {"product": product, "shifts_detected": len(all_shifts), "shifts": all_shifts}

    def _detect_shifts(self, product: str, competitor: str) -> list[dict]:
        try:
            from shared.search import search as _search
            results = _search(f"{competitor} pricing features announcement 2025 2026", num_results=6)
        except Exception:
            return []

        snippets = "\n".join(f"- {r.get('title','')}: {r.get('snippet','')}" for r in results)
        resp = llm.complete(
            messages=[{"role": "user", "content": f"Competitor: {competitor}\nResults:\n{snippets}"}],
            system=_SYSTEM,
            max_tokens=400,
        )
        raw = resp.content[0].text.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []

        if not parsed.get("shifts_detected"):
            return []

        for shift in parsed.get("shifts", []):
            self._db.save_signal(
                signal_type="pricing" if "pric" in shift.get("type", "").lower() else "news",
                headline=shift.get("description", "")[:500],
                product=product,
                competitor=competitor,
                relevance_score=9 if shift.get("impact") == "high" else 6,
                summary=shift.get("description", "")[:200],
            )
        return parsed.get("shifts", [])

    def _notify_strategy(self, product: str, shifts: list[dict]) -> None:
        try:
            TaskQueue().push(
                agent="strategy",
                payload={"action": "market_shift", "product": product, "shifts": shifts, "source": "intel"},
            )
        except Exception as exc:
            logger.warning("notify_strategy_failed", error=str(exc))
