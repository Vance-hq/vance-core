"""Auto-remediation for high CPU, memory, and disk conditions."""

from __future__ import annotations

import subprocess
from typing import Any

import httpx
import psutil

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import ScalingDB

logger = get_logger(__name__)

_DOCKER_SOCK = "/var/run/docker.sock"
_LOG_PRUNE_DAYS = 30
_LOG_DIRS = ["/var/log", "/app/logs"]


class AutoRemediation:

    def __init__(self, cfg: dict, db: ScalingDB | None = None) -> None:
        self._cfg = cfg
        self._db = db or ScalingDB()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def remediate(self, trigger: str, value: float) -> dict:
        """
        Attempt automatic remediation based on trigger metric.
        Returns {"trigger", "action_taken", "outcome", "details"}.
        """
        handlers = {
            "memory_pct": self._handle_high_memory,
            "disk_pct": self._handle_high_disk,
            "cpu_pct": self._handle_high_cpu,
        }
        handler = handlers.get(trigger)
        if not handler:
            result = {"trigger": trigger, "action_taken": "none", "outcome": "no_action", "details": {}}
            self._log_event(result)
            return result

        try:
            result = handler(value)
        except Exception as exc:
            logger.error("remediation_failed", trigger=trigger, error=str(exc))
            result = {
                "trigger": trigger,
                "action_taken": "remediation_attempted",
                "outcome": "failed",
                "details": {"error": str(exc)},
            }

        self._log_event(result)
        return result

    # ------------------------------------------------------------------
    # High memory: identify and restart the top memory container
    # ------------------------------------------------------------------

    def _handle_high_memory(self, value: float) -> dict:
        container = self._find_top_memory_container()
        if not container:
            return {
                "trigger": "memory_pct",
                "action_taken": "identify_top_container",
                "outcome": "no_container_found",
                "details": {"memory_pct": value},
            }

        self._restart_container(container["id"])
        logger.info("container_restarted", name=container["name"], memory_pct=value)
        return {
            "trigger": "memory_pct",
            "action_taken": f"restart_container:{container['name']}",
            "outcome": "success",
            "details": {"container": container["name"], "memory_pct": value},
        }

    # ------------------------------------------------------------------
    # High disk: clear old logs + Docker image cache
    # ------------------------------------------------------------------

    def _handle_high_disk(self, value: float) -> dict:
        freed_bytes = 0

        # Prune log files older than 30 days
        for log_dir in _LOG_DIRS:
            try:
                result = subprocess.run(
                    ["find", log_dir, "-type", "f", "-mtime", f"+{_LOG_PRUNE_DAYS}", "-delete"],
                    capture_output=True, timeout=60,
                )
                logger.info("log_pruned", dir=log_dir, returncode=result.returncode)
            except Exception as exc:
                logger.warning("log_prune_failed", dir=log_dir, error=str(exc))

        # Prune dangling Docker images
        try:
            result = subprocess.run(
                ["docker", "image", "prune", "-f"],
                capture_output=True, text=True, timeout=120,
            )
            output = result.stdout.strip()
            logger.info("docker_image_pruned", output=output)
        except Exception as exc:
            logger.warning("docker_prune_failed", error=str(exc))

        after = psutil.disk_usage("/").percent
        return {
            "trigger": "disk_pct",
            "action_taken": "prune_logs_and_images",
            "outcome": "success",
            "details": {"disk_before_pct": value, "disk_after_pct": after},
        }

    # ------------------------------------------------------------------
    # High CPU: identify top process, alert if unexpected
    # ------------------------------------------------------------------

    def _handle_high_cpu(self, value: float) -> dict:
        top = self._top_cpu_process()
        unexpected = self._is_unexpected_process(top["name"])

        details: dict[str, Any] = {
            "cpu_pct": value,
            "top_process": top,
            "unexpected": unexpected,
        }

        if unexpected:
            logger.warning("unexpected_high_cpu_process", **top)
            TaskQueue().push(
                agent="reporting",
                payload={
                    "action": "add_to_brief",
                    "category": "unexpected_cpu_spike",
                    "data": details,
                },
                priority=3,
            )

        return {
            "trigger": "cpu_pct",
            "action_taken": "identify_top_process",
            "outcome": "success",
            "details": details,
        }

    # ------------------------------------------------------------------
    # Docker socket helpers
    # ------------------------------------------------------------------

    def _find_top_memory_container(self) -> dict | None:
        try:
            transport = httpx.HTTPTransport(uds=_DOCKER_SOCK)
            with httpx.Client(transport=transport, base_url="http://docker") as client:
                resp = client.get("/containers/json", timeout=5)
                resp.raise_for_status()
                containers = resp.json()

            best = None
            best_mem = -1.0
            for c in containers:
                cid = c["Id"]
                cname = (c.get("Names") or ["?"])[0].lstrip("/")
                try:
                    with httpx.Client(transport=transport, base_url="http://docker") as client:
                        stat = client.get(
                            f"/containers/{cid}/stats",
                            params={"stream": "false"},
                            timeout=10,
                        ).json()
                    mem = stat["memory_stats"]
                    usage = mem["usage"] - mem.get("stats", {}).get("cache", 0)
                    limit = mem["limit"]
                    pct = usage / limit * 100 if limit else 0.0
                    if pct > best_mem:
                        best_mem = pct
                        best = {"id": cid, "name": cname, "mem_pct": pct}
                except Exception:
                    pass
            return best
        except Exception as exc:
            logger.debug("docker_mem_query_failed", error=str(exc))
            return None

    def _restart_container(self, container_id: str) -> None:
        transport = httpx.HTTPTransport(uds=_DOCKER_SOCK)
        with httpx.Client(transport=transport, base_url="http://docker") as client:
            resp = client.post(f"/containers/{container_id}/restart", timeout=30)
            resp.raise_for_status()

    # ------------------------------------------------------------------
    # Process helpers (psutil)
    # ------------------------------------------------------------------

    def _top_cpu_process(self) -> dict:
        procs = [
            {"pid": p.pid, "name": p.name(), "cpu_pct": p.cpu_percent(interval=1)}
            for p in psutil.process_iter(["pid", "name"])
        ]
        procs.sort(key=lambda x: x["cpu_pct"], reverse=True)
        return procs[0] if procs else {"pid": 0, "name": "unknown", "cpu_pct": 0.0}

    def _is_unexpected_process(self, name: str) -> bool:
        known = set(self._cfg.get("known_processes", [
            "python3", "python", "node", "nginx", "postgres", "redis-server",
            "celery", "docker", "dockerd", "containerd", "sshd", "systemd",
            "prometheus", "grafana", "loki", "promtail",
        ]))
        return name not in known

    # ------------------------------------------------------------------
    # DB logging
    # ------------------------------------------------------------------

    def _log_event(self, result: dict) -> None:
        try:
            self._db.insert_event(
                trigger=result["trigger"],
                action_taken=result["action_taken"],
                outcome=result["outcome"],
                metadata=result.get("details", {}),
            )
        except Exception as exc:
            logger.warning("scaling_event_log_failed", error=str(exc))
