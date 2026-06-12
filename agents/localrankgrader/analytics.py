"""Grader funnel analytics — daily metrics and weekly industry/city insights."""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger

from .db import GraderDB

logger = get_logger(__name__)


class GraderAnalytics:
    def __init__(self, db: GraderDB) -> None:
        self._db = db

    def daily_summary(self) -> dict[str, Any]:
        audit_count = self._db.daily_audit_count()
        lead_stats = self._db.daily_report_stats()
        funnel = self._db.funnel_stats()

        summary = {
            "period": "last_24h",
            "audits_run": audit_count,
            "leads_created": lead_stats.get("total_leads", 0),
            "trials_started": lead_stats.get("trials_started", 0),
            "conversions": lead_stats.get("conversions", 0),
            "avg_score": float(lead_stats.get("avg_score") or 0),
            "funnel_7d": {
                "audits": funnel.get("audits_total", 0),
                "reports_delivered": funnel.get("reports_delivered", 0),
                "leads": funnel.get("leads_created", 0),
                "email_engaged": funnel.get("email_engaged", 0),
                "trials": funnel.get("trials_started", 0),
            },
        }
        if summary["funnel_7d"]["audits"]:
            summary["funnel_7d"]["audit_to_trial_rate"] = round(
                summary["funnel_7d"]["trials"] / summary["funnel_7d"]["audits"] * 100, 1
            )

        logger.info("grader_daily_summary", **{k: v for k, v in summary.items() if not isinstance(v, dict)})
        return summary

    def weekly_industry_report(self) -> dict[str, Any]:
        top = self._db.top_industries_cities(days=7)
        return {
            "period": "last_7d",
            "top_industries_cities": top,
        }
