"""OnDemandReporter — generates focused reports from voice commands via intent-based data queries."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import ReportingDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are Vance, Dutch's AI chief of staff. "
    "Dutch has asked a specific question. Answer it directly and concisely based on the data provided. "
    "Lead with the direct answer, then supporting context. "
    "Keep the response under 100 words — it will be spoken aloud. "
    "If no relevant data is available, say so plainly and suggest how to get it."
)

# How many days of history to pull for on-demand queries
_LOOKBACK_DAYS = 30


class OnDemandReporter:

    def __init__(self, db: ReportingDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def generate(
        self,
        intent: str,
        product: str | None = None,
        save: bool = False,
    ) -> dict[str, Any]:
        today = date.today().isoformat()
        from_date = (date.today() - timedelta(days=_LOOKBACK_DAYS)).isoformat()

        items = self._db.get_brief_items_range(from_date=from_date, to_date=today)

        # Filter by product if specified
        if product:
            filtered = [
                i for i in items
                if str(i.get("data", {}).get("product", "")).lower() == product.lower()
                or str(i.get("source", "")).lower() == product.lower()
            ]
            # Fall back to all items if product filter yields nothing
            data_items = filtered if filtered else items
        else:
            data_items = items

        sections: dict[str, list] = {}
        for item in data_items:
            sections.setdefault(item["section"], []).append(item["data"])

        prompt_parts = [f'Dutch asked: "{intent}"']
        if product:
            prompt_parts.append(f"Focus on product: {product}")
        prompt_parts.append(f"\nAvailable data (last {_LOOKBACK_DAYS} days):")
        prompt_parts.append(json.dumps(sections, default=str, indent=2) if sections else "(no data)")
        prompt = "\n".join(prompt_parts)

        try:
            resp = llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system=_SYSTEM,
                max_tokens=300,
            )
            report_text = resp.content[0].text.strip()
        except Exception as exc:
            logger.warning("on_demand_reporter_llm_failed", error=str(exc))
            report_text = "I couldn't generate that report right now. Please try again in a moment."

        self._deliver_via_voice(report_text, intent)

        report_id: str | None = None
        if save:
            report_id = self._db.save_report(
                report_type="on_demand",
                content_text=report_text,
                period_date=today,
                product=product,
            )

        logger.info("on_demand_report_generated", intent=intent, product=product, saved=save)
        return {
            "intent": intent,
            "product": product,
            "report": report_text,
            "report_id": report_id,
            "saved": save,
        }

    def _deliver_via_voice(self, text: str, intent: str) -> None:
        try:
            TaskQueue().push(
                "voice",
                {
                    "action": "speak",
                    "text": text,
                    "priority": "high",
                    "source": "on_demand_report",
                    "intent": intent,
                },
            )
        except Exception as exc:
            logger.warning("on_demand_voice_failed", error=str(exc))
