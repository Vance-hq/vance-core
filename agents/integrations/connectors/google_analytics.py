"""Google Analytics 4 (Data API) connector."""
from __future__ import annotations

from typing import Any

from shared.config.settings import settings

from ._google_auth import get_google_access_token
from .base_connector import BaseConnector

_BASE = "https://analyticsdata.googleapis.com/v1beta"


class GoogleAnalyticsConnector(BaseConnector):
    service_name = "google_analytics"
    _rate_limit_config = (10, 1)  # GA4 core reporting: ~10 qps

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {
            "refresh_token": settings.GA4_REFRESH_TOKEN,
            "property_id": settings.GA4_PROPERTY_ID,
        }

    def _token(self) -> str:
        return get_google_access_token(self._redis, "ga4", settings.GA4_REFRESH_TOKEN)

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    def _report(self, body: dict) -> dict:
        prop = settings.GA4_PROPERTY_ID
        resp = self.request(
            "POST",
            f"{_BASE}/properties/{prop}:runReport",
            headers=self._auth(),
            json=body,
        )
        return resp.json()

    # ------------------------------------------------------------------

    def get_sessions(
        self,
        start_date: str = "7daysAgo",
        end_date: str = "today",
    ) -> dict:
        return self._report({
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "metrics": [{"name": "sessions"}, {"name": "activeUsers"}, {"name": "bounceRate"}],
        })

    def get_conversions(
        self,
        goal_name: str,
        start_date: str = "30daysAgo",
        end_date: str = "today",
    ) -> dict:
        return self._report({
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "metrics": [{"name": "conversions"}, {"name": "eventCount"}],
            "dimensionFilter": {
                "filter": {
                    "fieldName": "eventName",
                    "stringFilter": {"value": goal_name},
                }
            },
        })

    def get_top_pages(
        self,
        limit: int = 10,
        start_date: str = "7daysAgo",
        end_date: str = "today",
    ) -> dict:
        return self._report({
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "pagePath"}],
            "metrics": [{"name": "screenPageViews"}, {"name": "averageSessionDuration"}],
            "limit": limit,
            "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
        })

    def get_traffic_sources(
        self,
        start_date: str = "30daysAgo",
        end_date: str = "today",
    ) -> dict:
        return self._report({
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "sessionSource"}, {"name": "sessionMedium"}],
            "metrics": [{"name": "sessions"}, {"name": "conversions"}],
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        })

    def get_user_cohorts(
        self,
        start_date: str = "90daysAgo",
        end_date: str = "today",
    ) -> dict:
        return self._report({
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "firstSessionDate"}],
            "metrics": [{"name": "activeUsers"}, {"name": "sessions"}],
            "orderBys": [{"dimension": {"dimensionName": "firstSessionDate"}, "desc": False}],
        })
