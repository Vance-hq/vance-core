"""90-day revenue forecast using LLM with low/base/high scenarios."""

from __future__ import annotations

import json
import re

from shared.llm.client import llm
from shared.logger import get_logger

from .db import FinanceDB

logger = get_logger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_FORECAST_PROMPT = """You are a SaaS financial analyst. Given the MRR history below, produce a 90-day revenue forecast.

Return ONLY valid JSON with this exact structure:
{{
  "low": {{"mrr_cents": <int>, "arr_cents": <int>, "assumption": "<string>"}},
  "base": {{"mrr_cents": <int>, "arr_cents": <int>, "assumption": "<string>"}},
  "high": {{"mrr_cents": <int>, "arr_cents": <int>, "assumption": "<string>"}},
  "key_risks": ["<string>", ...],
  "key_opportunities": ["<string>", ...]
}}

MRR history (most recent first, in cents):
{history}

Current MRR: {current_mrr_cents} cents (${current_mrr_usd:.2f}/month)
"""


class Forecaster:
    def __init__(self, config: dict, db: FinanceDB | None = None) -> None:
        self._cfg = config
        self._db = db or FinanceDB()

    def forecast(self, product: str = "default") -> dict:
        history = self._db.get_mrr_history(product=product, days=90)
        if not history:
            return self._empty_forecast("no_data")

        current_mrr = history[0]["mrr_cents"] if history else 0
        history_summary = [
            {"date": str(r["snapshot_date"]), "mrr_cents": r["mrr_cents"]}
            for r in history[:30]
        ]

        prompt = _FORECAST_PROMPT.format(
            history=json.dumps(history_summary, indent=2),
            current_mrr_cents=current_mrr,
            current_mrr_usd=current_mrr / 100,
        )

        try:
            raw = llm.complete(prompt)
            match = _JSON_RE.search(raw)
            if not match:
                logger.warning("forecast_parse_failed", raw=raw[:200])
                return self._empty_forecast("parse_error")
            result = json.loads(match.group())
        except Exception as exc:
            logger.error("forecast_llm_error", error=str(exc))
            return self._empty_forecast("llm_error")

        result["product"] = product
        result["current_mrr_cents"] = current_mrr
        result["horizon_days"] = 90
        return result

    def _empty_forecast(self, reason: str) -> dict:
        return {
            "low": {"mrr_cents": 0, "arr_cents": 0, "assumption": reason},
            "base": {"mrr_cents": 0, "arr_cents": 0, "assumption": reason},
            "high": {"mrr_cents": 0, "arr_cents": 0, "assumption": reason},
            "key_risks": [],
            "key_opportunities": [],
            "current_mrr_cents": 0,
            "horizon_days": 90,
            "error": reason,
        }
