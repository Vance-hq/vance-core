"""LLM-powered report generator — produces JSON metrics + narrative summary."""
from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from shared.logger import get_logger

if TYPE_CHECKING:
    from .db import AnalyticsDB

logger = get_logger(__name__)

_SUMMARY_SYSTEM = (
    "You are a growth analyst for a SaaS company. "
    "Summarise the provided metrics in 3-5 bullet points. "
    "Flag anomalies and actionable opportunities. "
    "Be concise — each bullet under 20 words. "
    "Use → to denote a recommended action."
)


class AnalyticsReporter:
    def __init__(self, db: "AnalyticsDB", ask_llm_fn) -> None:
        self._db = db
        self._ask_llm = ask_llm_fn

    def build_growth_dashboard(
        self,
        stripe_metrics: dict,
        posthog_metrics: dict,
        ga4_metrics: dict,
        ttl_seconds: int = 3600,
    ) -> dict:
        payload: dict[str, Any] = {
            "revenue": stripe_metrics,
            "behavior": posthog_metrics,
            "web": ga4_metrics,
        }
        summary = self._ask_llm(
            f"Metrics snapshot:\n{json.dumps(payload, default=str, indent=2)}",
            system_prompt=_SUMMARY_SYSTEM,
        )
        report = {**payload, "summary": summary}
        self._db.upsert_report("growth_dashboard", report, ttl_seconds=ttl_seconds)
        return report

    def build_product_usage_report(
        self,
        top_features: list[dict],
        funnel: list[dict],
        ttl_seconds: int = 3600,
    ) -> dict:
        payload: dict[str, Any] = {"top_features": top_features, "funnel": funnel}
        summary = self._ask_llm(
            f"Product usage data:\n{json.dumps(payload, default=str, indent=2)}",
            system_prompt=_SUMMARY_SYSTEM,
        )
        report = {**payload, "summary": summary}
        self._db.upsert_report("product_usage", report, ttl_seconds=ttl_seconds)
        return report
