"""PivotDetector — detects when a product strategy isn't working and surfaces diagnosis before action."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import StrategyDB

logger = get_logger(__name__)

# Trigger thresholds
_DECLINING_WEEKS_THRESHOLD = 3
_CONVERSION_RATE_THRESHOLD = 0.01  # 1%

_SYSTEM = (
    "You are a SaaS strategic advisor. A product is showing warning signals. "
    "Diagnose what is failing and generate exactly 3 strategic options. "
    "Output JSON only:\n"
    "{\"diagnosis\": str, "
    "\"options\": [{\"option\": str, \"rationale\": str}], "
    "\"recommended_option\": str}\n\n"
    "Be blunt. Name the root cause. The recommended_option must match one of the options exactly."
)


class PivotDetector:

    def __init__(self, db: StrategyDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def detect(self, product: str) -> dict[str, Any]:
        triggered, reason = self._check_triggers(product)

        if not triggered:
            return {"product": product, "triggered": False, "reason": None}

        diagnosis, options, recommended_option = self._run_diagnosis(product=product, reason=reason)

        alert_id = self._db.save_pivot_alert(
            product=product,
            diagnosis=diagnosis,
            options=options,
            recommended_option=recommended_option,
        )

        self._deliver_priority_alert(product=product, diagnosis=diagnosis, recommended_option=recommended_option)

        logger.info("pivot_detected", product=product, reason=reason, alert_id=alert_id)
        return {
            "product": product,
            "triggered": True,
            "reason": reason,
            "alert_id": alert_id,
            "diagnosis": diagnosis,
            "options": options,
            "recommended_option": recommended_option,
        }

    def _check_triggers(self, product: str) -> tuple[bool, str | None]:
        # Check MRR trend: 3 consecutive declining weeks
        mrr_data = self._db.get_mrr_trend(product=product, weeks=_DECLINING_WEEKS_THRESHOLD)
        if self._is_declining(mrr_data):
            return True, "declining_mrr_3_consecutive_weeks"

        # Check conversion rate: below 1% for 30 days
        conversion_rate = self._db.get_conversion_rate(product=product, days=30)
        if conversion_rate > 0 and conversion_rate < _CONVERSION_RATE_THRESHOLD:
            return True, f"conversion_rate_below_1pct_{conversion_rate:.3f}"

        return False, None

    def _is_declining(self, mrr_data: list[dict]) -> bool:
        if len(mrr_data) < _DECLINING_WEEKS_THRESHOLD:
            return False
        values = [d.get("mrr", 0) for d in mrr_data]
        # All consecutive pairs must be declining
        return all(values[i] > values[i + 1] for i in range(len(values) - 1))

    def _run_diagnosis(self, product: str, reason: str) -> tuple[str, list[dict], str]:
        signals = self._db.list_signals(product=product, actioned=False, limit=15)
        signal_lines = [f"- [{s['signal_type']}] {s['summary']}" for s in signals]

        prompt = (
            f"Product: {product}\n"
            f"Trigger: {reason}\n\n"
            f"Recent signals:\n" + ("\n".join(signal_lines) or "No signals recorded.")
        )

        try:
            resp = llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system=_SYSTEM,
                max_tokens=700,
            )
            raw = resp.content[0].text.strip()
            parsed = json.loads(raw)
            diagnosis = parsed.get("diagnosis", "Strategy review required.")
            options = parsed.get("options", [])
            recommended_option = parsed.get("recommended_option", options[0]["option"] if options else "")
        except Exception as exc:
            logger.warning("pivot_detector_llm_failed", error=str(exc))
            diagnosis = f"Strategy review required for {product}. Trigger: {reason}."
            options = [
                {"option": "Investigate root cause", "rationale": "Understand before acting"},
                {"option": "Pause paid acquisition", "rationale": "Stop spending while diagnosing"},
                {"option": "Run user interviews", "rationale": "Direct customer feedback"},
            ]
            recommended_option = "Investigate root cause"

        return diagnosis, options, recommended_option

    def _deliver_priority_alert(self, product: str, diagnosis: str, recommended_option: str) -> None:
        try:
            text = (
                f"Priority strategy alert for {product}. "
                f"Diagnosis: {diagnosis} "
                f"Recommended action: {recommended_option}. "
                "Your review is required before any changes are made."
            )
            TaskQueue().push(
                "voice",
                {
                    "action": "speak",
                    "text": text,
                    "priority": "urgent",
                    "source": "pivot_detector",
                    "product": product,
                },
            )
        except Exception as exc:
            logger.warning("pivot_detector_voice_failed", error=str(exc))
