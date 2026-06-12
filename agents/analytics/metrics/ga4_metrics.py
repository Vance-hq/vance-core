"""Google Analytics 4 web metrics via GoogleAnalyticsConnector."""
from __future__ import annotations

from typing import Any

from agents.integrations.connectors.google_analytics import GoogleAnalyticsConnector
from shared.logger import get_logger

logger = get_logger(__name__)


class GA4Metrics:
    def __init__(self, task_id: str | None = None) -> None:
        self._ga4 = GoogleAnalyticsConnector(
            task_id=task_id,
            called_by="analytics",
            method_name="ga4_metrics",
        )

    def web_overview(self, days: int = 7) -> dict[str, Any]:
        date_range = f"{days}daysAgo"
        sessions_resp = self._ga4.get_sessions(start_date=date_range)
        traffic_resp = self._ga4.get_traffic_sources(start_date=date_range)
        pages_resp = self._ga4.get_top_pages(limit=5, start_date=date_range)

        def _first_metric(resp: dict) -> dict:
            rows = resp.get("rows", [])
            if not rows:
                return {}
            return {
                m["name"]: rows[0]["metricValues"][i]["value"]
                for i, m in enumerate(resp.get("metricHeaders", []))
            }

        def _tabulate(resp: dict, dim_count: int = 1) -> list[dict]:
            rows = []
            dim_headers = [h["name"] for h in resp.get("dimensionHeaders", [])]
            met_headers = [h["name"] for h in resp.get("metricHeaders", [])]
            for r in resp.get("rows", []):
                row: dict[str, Any] = {}
                for i, h in enumerate(dim_headers):
                    row[h] = r["dimensionValues"][i]["value"]
                for i, h in enumerate(met_headers):
                    row[h] = r["metricValues"][i]["value"]
                rows.append(row)
            return rows

        return {
            "sessions": _first_metric(sessions_resp),
            "traffic_sources": _tabulate(traffic_resp),
            "top_pages": _tabulate(pages_resp),
        }

    def conversion_events(self, goal_name: str = "generate_lead", days: int = 30) -> dict:
        resp = self._ga4.get_conversions(goal_name=goal_name, start_date=f"{days}daysAgo")
        rows = resp.get("rows", [])
        if not rows:
            return {"conversions": 0, "event_count": 0}
        metrics = resp.get("metricHeaders", [])
        result = {}
        for i, m in enumerate(metrics):
            result[m["name"]] = rows[0]["metricValues"][i]["value"]
        return result
