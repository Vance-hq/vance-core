"""Security agent — uptime monitoring, log scanning, alerting."""

from __future__ import annotations

import subprocess
from typing import Any

import httpx

from agents._base import BaseAgent, AgentConfig
from agents.integrations.connectors.slack import SlackConnector
from shared.config.settings import settings
from shared.logger import get_logger
from shared.types import Task, TaskResult

logger = get_logger(__name__)

UPTIME_TARGETS = [
    "https://vance.so/health",
    "http://localhost:7700/health",   # orchestrator
    "http://localhost:8080/health",   # webhooks
]


class SecurityAgent(BaseAgent):

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")

        if action == "check_uptime":
            return self._check_uptime(task)
        if action == "scan_logs":
            return self._scan_logs(task)
        if action == "send_alert":
            return self._send_alert(task)

        return TaskResult(task_id=task.id, success=False, output={"error": f"unknown action: {action}"})

    def health_check(self) -> bool:
        return True

    # ------------------------------------------------------------------

    def _check_uptime(self, task: Task) -> TaskResult:
        targets = task.payload.get("targets", UPTIME_TARGETS)
        results = {}
        with httpx.Client(timeout=10) as client:
            for url in targets:
                try:
                    resp = client.get(url)
                    results[url] = {"status": resp.status_code, "ok": resp.is_success}
                except Exception as exc:
                    results[url] = {"status": None, "ok": False, "error": str(exc)}

        failures = [u for u, r in results.items() if not r["ok"]]
        if failures:
            self._alert(f"Uptime failures: {', '.join(failures)}")

        return TaskResult(task_id=task.id, success=True, output={"results": results, "failures": failures})

    def _scan_logs(self, task: Task) -> TaskResult:
        pattern = task.payload.get("pattern", "ERROR")
        log_path = task.payload.get("log_path", "/app/logs")
        lines = task.payload.get("lines", 500)

        result = subprocess.run(
            ["grep", "-r", pattern, log_path, "--include=*.log", f"-m{lines}"],
            capture_output=True,
            text=True,
        )
        matches = result.stdout.strip().splitlines() if result.stdout else []
        if len(matches) > 10:
            self._alert(f"Log scan found {len(matches)} '{pattern}' matches in {log_path}")

        return TaskResult(task_id=task.id, success=True, output={"matches": matches[:50], "count": len(matches)})

    def _send_alert(self, task: Task) -> TaskResult:
        message = task.payload.get("message", "")
        self._alert(message)
        return TaskResult(task_id=task.id, success=True, output={"sent": True})

    def _alert(self, message: str) -> None:
        try:
            slack = SlackConnector(called_by="security", method_name="send_message")
            slack.send_message(channel=settings.SECURITY_ALERT_CHANNEL or "#ops", text=f":warning: *Security Alert*\n{message}")
        except Exception as exc:
            logger.error("alert_send_failed", error=str(exc))


if __name__ == "__main__":
    config = AgentConfig.load("security")
    SecurityAgent("security", config).run()
