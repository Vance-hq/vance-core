"""UsageCollector — pulls daily usage metrics from Umami and Supabase per product."""

from __future__ import annotations

from datetime import date
from typing import Any

from shared.logger import get_logger

from .db import AnalyticsDB

logger = get_logger(__name__)


def _fetch_umami(base_url: str, api_key: str, website_id: str, date_str: str) -> dict[str, Any]:
    try:
        import httpx
        start_ms = int(date(*[int(x) for x in date_str.split("-")]).toordinal() * 86400000)
        end_ms = start_ms + 86399999
        resp = httpx.get(
            f"{base_url}/api/websites/{website_id}/stats",
            headers={"x-umami-api-key": api_key},
            params={"startAt": start_ms, "endAt": end_ms},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "site_visits": data.get("pageviews", {}).get("value", 0),
            "unique_visitors": data.get("visitors", {}).get("value", 0),
            "sessions": data.get("sessions", {}).get("value", 0),
        }
    except Exception as exc:
        logger.warning("umami_fetch_failed", error=str(exc))
        return {}


def _fetch_supabase_metrics(
    supabase_url: str,
    service_key: str,
    queries: list[dict[str, str]],
    date_str: str,
) -> dict[str, Any]:
    """Run named SQL queries against Supabase REST API, return {metric_name: count}."""
    try:
        import httpx
        results: dict[str, Any] = {}
        headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }
        for q in queries:
            name = q["name"]
            sql = q["sql"].replace("{date}", date_str)
            resp = httpx.post(
                f"{supabase_url}/rest/v1/rpc/analytics_query",
                headers=headers,
                json={"query": sql},
                timeout=10,
            )
            if resp.status_code == 200:
                rows = resp.json()
                results[name] = rows[0]["count"] if rows else 0
            else:
                results[name] = 0
    except Exception as exc:
        logger.warning("supabase_metrics_fetch_failed", error=str(exc))
        results = {}
    return results


class UsageCollector:

    def __init__(self, db: AnalyticsDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str, date_str: str | None = None) -> dict[str, Any]:
        today = date_str or date.today().isoformat()
        prod_cfg = self._cfg.get("products", {}).get(product, {})

        metrics: dict[str, Any] = {}

        # Umami — web traffic
        umami_cfg = self._cfg.get("umami", {})
        website_id = prod_cfg.get("umami_website_id", "")
        if umami_cfg.get("base_url") and website_id:
            web = _fetch_umami(
                base_url=umami_cfg["base_url"],
                api_key=umami_cfg.get("api_key", ""),
                website_id=website_id,
                date_str=today,
            )
            metrics.update(web)

        # Supabase — in-app activity
        supabase_cfg = self._cfg.get("supabase", {})
        queries = prod_cfg.get("supabase_queries", [])
        if supabase_cfg.get("url") and queries:
            app = _fetch_supabase_metrics(
                supabase_url=supabase_cfg["url"],
                service_key=supabase_cfg.get("service_key", ""),
                queries=queries,
                date_str=today,
            )
            metrics.update(app)

        self._db.upsert_usage_snapshot(product=product, date=today, metrics=metrics)
        logger.info("usage_snapshot_stored", product=product, date=today, keys=list(metrics.keys()))

        return {"product": product, "date": today, "metrics": metrics}
