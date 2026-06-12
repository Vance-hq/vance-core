"""PostHog behavioral metrics — DAUs, funnel, feature adoption."""
from __future__ import annotations

from typing import Any

import httpx

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)


class PostHogMetrics:
    def __init__(self) -> None:
        host = settings.POSTHOG_HOST.rstrip("/")
        project_id = settings.POSTHOG_PROJECT_ID
        self._base = f"{host}/api/projects/{project_id}"
        self._headers = {
            "Authorization": f"Bearer {settings.POSTHOG_API_KEY}",
            "Content-Type": "application/json",
        }

    def _hogql(self, query: str) -> list[list]:
        """Run a HogQL query and return raw result rows."""
        resp = httpx.post(
            f"{self._base}/query/",
            headers=self._headers,
            json={"query": {"kind": "HogQLQuery", "query": query}},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])

    def _scalar(self, query: str, default: float = 0.0) -> float:
        rows = self._hogql(query)
        return float(rows[0][0]) if rows and rows[0] else default

    # ------------------------------------------------------------------

    def daily_active_users(self, days: int = 7) -> float:
        return self._scalar(
            f"SELECT count(distinct person_id) FROM events "
            f"WHERE timestamp >= now() - interval {days} day"
        )

    def session_count(self, days: int = 7) -> float:
        return self._scalar(
            f"SELECT count(distinct session_id) FROM events "
            f"WHERE timestamp >= now() - interval {days} day AND session_id IS NOT NULL"
        )

    def funnel(self, events: list[str], days: int = 30) -> list[dict]:
        """Return step-by-step conversion counts for an ordered event funnel."""
        results = []
        previous_count: float | None = None
        for event in events:
            count = self._scalar(
                f"SELECT count(distinct person_id) FROM events "
                f"WHERE event = '{event}' AND timestamp >= now() - interval {days} day"
            )
            conversion = (count / previous_count) if previous_count and previous_count > 0 else None
            results.append({
                "event": event,
                "unique_users": count,
                "conversion_from_previous": round(conversion, 4) if conversion is not None else None,
            })
            previous_count = count
        return results

    def top_features(self, days: int = 7, limit: int = 20) -> list[dict]:
        """Return the most-used custom events (excluding PostHog system events)."""
        rows = self._hogql(
            f"""
            SELECT event, count() as cnt, count(distinct person_id) as unique_users
            FROM events
            WHERE timestamp >= now() - interval {days} day
              AND event NOT LIKE '$%'
            GROUP BY event
            ORDER BY cnt DESC
            LIMIT {limit}
            """
        )
        return [{"event": r[0], "count": r[1], "unique_users": r[2]} for r in rows]

    def conversion_rate(
        self,
        from_event: str,
        to_event: str,
        days: int = 30,
    ) -> float:
        top = self._scalar(
            f"SELECT count(distinct person_id) FROM events "
            f"WHERE event = '{from_event}' AND timestamp >= now() - interval {days} day"
        )
        bottom = self._scalar(
            f"SELECT count(distinct person_id) FROM events "
            f"WHERE event = '{to_event}' AND timestamp >= now() - interval {days} day"
        )
        return round(bottom / top, 4) if top > 0 else 0.0

    def new_users(self, days: int = 30) -> float:
        return self._scalar(
            f"SELECT count(distinct id) FROM persons "
            f"WHERE created_at >= now() - interval {days} day"
        )

    def retention_by_week(self, weeks: int = 8) -> list[dict]:
        """Weekly active users to approximate retention."""
        rows = self._hogql(
            f"""
            SELECT
                toStartOfWeek(timestamp) as week,
                count(distinct person_id) as active_users
            FROM events
            WHERE timestamp >= now() - interval {weeks} week
            GROUP BY week
            ORDER BY week DESC
            """
        )
        return [{"week": str(r[0]), "active_users": r[1]} for r in rows]
