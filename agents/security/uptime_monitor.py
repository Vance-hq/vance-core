"""Uptime monitor — polls services every 60s, fires CRITICAL alerts on downtime."""

from __future__ import annotations

import time
from typing import Any

import httpx

from shared.config.settings import settings
from shared.logger import get_logger

from .db import SecurityDB

logger = get_logger(__name__)

DEFAULT_TARGETS = [
    "https://vance.so/health",
    "https://starpio.com/health",
    "https://oneserv.app/health",
    "http://localhost:7700/health",
    "http://localhost:8080/health",
]


class UptimeMonitor:

    def __init__(self, db: SecurityDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._targets: list[str] = cfg.get("uptime_targets", DEFAULT_TARGETS)
        self._kuma_url: str = cfg.get("uptime_kuma_url", settings.UPTIME_KUMA_URL)
        self._timeout: int = cfg.get("uptime_timeout_s", 10)

    # ------------------------------------------------------------------

    def check_all(self) -> dict[str, Any]:
        """Check HTTP targets + Uptime Kuma monitors. Return combined results."""
        http_results = self.check_targets(self._targets)
        kuma_results = self.check_uptime_kuma()

        failures = [u for u, r in http_results.items() if not r["ok"]]
        kuma_failures = [m for m, r in kuma_results.items() if not r.get("ok", True)]

        return {
            "http": http_results,
            "kuma": kuma_results,
            "failures": failures + kuma_failures,
            "all_ok": not failures and not kuma_failures,
        }

    def check_targets(self, targets: list[str]) -> dict[str, Any]:
        """HTTP GET each URL. Logs every check to DB. Returns per-URL result dict."""
        results: dict[str, Any] = {}
        with httpx.Client(timeout=self._timeout) as client:
            for url in targets:
                start = time.monotonic()
                try:
                    resp = client.get(url)
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    ok = resp.is_success
                    results[url] = {
                        "ok": ok,
                        "status": resp.status_code,
                        "response_time_ms": elapsed_ms,
                    }
                    self._db.log_uptime(
                        service=url,
                        ok=ok,
                        status=resp.status_code,
                        response_time_ms=elapsed_ms,
                    )
                except Exception as exc:
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    results[url] = {"ok": False, "status": None, "error": str(exc)}
                    self._db.log_uptime(
                        service=url,
                        ok=False,
                        response_time_ms=elapsed_ms,
                        error=str(exc),
                    )
                    logger.warning("uptime_check_failed", url=url, error=str(exc))

        return results

    def check_uptime_kuma(self) -> dict[str, Any]:
        """Query Uptime Kuma's status-page JSON for all monitor statuses."""
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(f"{self._kuma_url}/api/status-page/default")
                if not resp.is_success:
                    return {}
                data = resp.json()
                monitors = data.get("publicGroupList", [])
                results: dict[str, Any] = {}
                for group in monitors:
                    for monitor in group.get("monitorList", []):
                        name = monitor.get("name", "unknown")
                        heartbeat = monitor.get("heartbeat", {})
                        ok = heartbeat.get("status", 0) == 1
                        results[name] = {
                            "ok": ok,
                            "status": heartbeat.get("status"),
                            "msg": heartbeat.get("msg", ""),
                        }
                        self._db.log_uptime(service=f"kuma:{name}", ok=ok)
                return results
        except Exception as exc:
            logger.warning("uptime_kuma_unreachable", error=str(exc))
            return {}
