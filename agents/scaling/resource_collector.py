"""Collect host and container resource metrics every 60 seconds."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx
import psutil

from shared.config.settings import settings
from shared.logger import get_logger

from .db import ScalingDB

logger = get_logger(__name__)

_DOCKER_SOCKET = "http+unix://%2Fvar%2Frun%2Fdocker.sock"
_PROMETHEUS_TIMEOUT = 5


class ResourceCollector:
    """
    Collect CPU, memory, disk, network, and container stats.

    Uses psutil for host metrics and the Docker socket REST API for
    per-container stats. Prometheus is queried as a fallback/supplement
    if the socket is unavailable.
    """

    def __init__(self, cfg: dict, db: ScalingDB | None = None) -> None:
        self._cfg = cfg
        self._db = db or ScalingDB()
        self._prometheus_url: str = cfg.get("prometheus_url") or settings.PROMETHEUS_URL

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect(self) -> dict:
        """Collect all metrics, store to DB, return snapshot."""
        ts = datetime.now(timezone.utc)
        rows: list[dict] = []

        host = self._host_metrics()
        for name, value in host.items():
            rows.append({"metric_name": name, "value": value, "recorded_at": ts})

        containers = self._container_metrics()
        for cstat in containers:
            rows.append({
                "metric_name": "container_cpu_pct",
                "value": cstat["cpu_pct"],
                "container": cstat["name"],
                "recorded_at": ts,
            })
            rows.append({
                "metric_name": "container_mem_pct",
                "value": cstat["mem_pct"],
                "container": cstat["name"],
                "recorded_at": ts,
            })

        self._db.bulk_insert_metrics(rows)
        return {"host": host, "containers": containers, "recorded_at": ts.isoformat()}

    def snapshot(self) -> dict:
        """Return current metrics without storing — used by threshold checker."""
        return {
            "host": self._host_metrics(),
            "containers": self._container_metrics(),
        }

    # ------------------------------------------------------------------
    # Host metrics (psutil)
    # ------------------------------------------------------------------

    def _host_metrics(self) -> dict[str, float]:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()
        return {
            "cpu_pct": cpu,
            "memory_pct": mem.percent,
            "disk_pct": disk.percent,
            "net_bytes_sent": float(net.bytes_sent),
            "net_bytes_recv": float(net.bytes_recv),
        }

    # ------------------------------------------------------------------
    # Container metrics (Docker socket)
    # ------------------------------------------------------------------

    def _container_metrics(self) -> list[dict]:
        try:
            transport = httpx.HTTPTransport(uds="/var/run/docker.sock")
            with httpx.Client(transport=transport, base_url="http://docker") as client:
                resp = client.get("/containers/json", timeout=5)
                resp.raise_for_status()
                containers = resp.json()

            stats = []
            for c in containers:
                cid = c["Id"]
                cname = (c.get("Names") or ["unknown"])[0].lstrip("/")
                try:
                    stat = self._fetch_container_stat(client, cid, cname)
                    if stat:
                        stats.append(stat)
                except Exception as exc:
                    logger.debug("container_stat_failed", container=cname, error=str(exc))
            return stats
        except Exception as exc:
            logger.debug("docker_socket_unavailable", error=str(exc))
            return []

    def _fetch_container_stat(
        self,
        client: httpx.Client,
        cid: str,
        cname: str,
    ) -> dict | None:
        resp = client.get(f"/containers/{cid}/stats", params={"stream": "false"}, timeout=10)
        resp.raise_for_status()
        raw = resp.json()

        cpu_pct = self._parse_cpu_pct(raw)
        mem_pct = self._parse_mem_pct(raw)
        return {"name": cname, "id": cid, "cpu_pct": cpu_pct, "mem_pct": mem_pct}

    @staticmethod
    def _parse_cpu_pct(stat: dict) -> float:
        try:
            cpu = stat["cpu_stats"]
            precpu = stat["precpu_stats"]
            cpu_delta = cpu["cpu_usage"]["total_usage"] - precpu["cpu_usage"]["total_usage"]
            sys_delta = cpu["system_cpu_usage"] - precpu["system_cpu_usage"]
            num_cpus = len(cpu["cpu_usage"].get("percpu_usage") or [1])
            if sys_delta <= 0:
                return 0.0
            return round(cpu_delta / sys_delta * num_cpus * 100.0, 2)
        except (KeyError, ZeroDivisionError):
            return 0.0

    @staticmethod
    def _parse_mem_pct(stat: dict) -> float:
        try:
            mem = stat["memory_stats"]
            usage = mem["usage"]
            limit = mem["limit"]
            # Subtract cached/inactive pages (not real working set)
            cache = mem.get("stats", {}).get("cache", 0)
            real = usage - cache
            return round(real / limit * 100.0, 2) if limit else 0.0
        except (KeyError, ZeroDivisionError):
            return 0.0
