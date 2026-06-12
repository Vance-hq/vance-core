"""
Security agent — Vance's immune system.

Actions:
  uptime_monitor          — HTTP + Uptime Kuma checks on all services
  intrusion_detect        — Log analysis, auto-block brute-force/attacks
  vulnerability_scan      — npm audit / pip-audit / Trivy CVE scanning
  ssl_cert_monitor        — SSL expiry tracking and auto-renew
  secrets_audit           — gitleaks scan across git history
  access_review           — Periodic access audit: GitHub / Vercel / Cloudflare
  ddos_response           — Traffic spike detection, Under Attack mode
  backup_integrity_check  — Verify backup agent ran within 25 hours

CRITICAL priority: intrusion_detect and ddos_response publish directly to
vance:security:alerts Redis channel — bypasses the standard task queue.
"""

from __future__ import annotations

import json
from typing import Any

import redis

from agents._base import AgentConfig, BaseAgent
from shared.config.settings import settings
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .access_reviewer import AccessReviewer
from .backup_checker import BackupChecker
from .db import SecurityDB
from .ddos_responder import DDoSResponder
from .intrusion_detector import IntrusionDetector
from .secrets_auditor import SecretsAuditor
from .ssl_monitor import SSLMonitor
from .uptime_monitor import UptimeMonitor
from .vuln_scanner import VulnScanner

logger = get_logger(__name__)

SECURITY_ALERTS_CHANNEL = "vance:security:alerts"


class SecurityAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = SecurityDB()
        self._uptime = UptimeMonitor(self._db, cfg)
        self._intrusion = IntrusionDetector(self._db, cfg)
        self._vuln = VulnScanner(self._db, cfg)
        self._ssl = SSLMonitor(self._db, cfg)
        self._secrets = SecretsAuditor(self._db, cfg)
        self._access = AccessReviewer(self._db, cfg)
        self._ddos = DDoSResponder(self._db, cfg)
        self._backup = BackupChecker(self._db, cfg)

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "uptime_monitor":         lambda: self._handle_uptime(p),
            "intrusion_detect":       lambda: self._handle_intrusion(p),
            "vulnerability_scan":     lambda: self._handle_vuln_scan(p),
            "ssl_cert_monitor":       lambda: self._handle_ssl(p),
            "secrets_audit":          lambda: self._handle_secrets(p),
            "access_review":          lambda: self._handle_access(p),
            "ddos_response":          lambda: self._handle_ddos(p),
            "backup_integrity_check": lambda: self._handle_backup(p),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown security action: {action}"},
            )

        logger.info("security_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.get_events(hours=1)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # uptime_monitor
    # ------------------------------------------------------------------

    def _handle_uptime(self, p: dict[str, Any]) -> dict[str, Any]:
        targets = p.get("targets")
        if targets:
            results = self._uptime.check_targets(targets)
            failures = [u for u, r in results.items() if not r["ok"]]
            if failures:
                self._critical_alert("uptime_failure", f"Services DOWN: {', '.join(failures)}", {"failures": failures})
            return {"results": results, "failures": failures}

        result = self._uptime.check_all()
        if result["failures"]:
            self._critical_alert(
                "uptime_failure",
                f"Services DOWN: {', '.join(result['failures'])}",
                {"failures": result["failures"]},
            )
        return result

    # ------------------------------------------------------------------
    # intrusion_detect
    # ------------------------------------------------------------------

    def _handle_intrusion(self, p: dict[str, Any]) -> dict[str, Any]:
        log_entries = p.get("log_entries") or []
        if not log_entries:
            logql = p.get("logql", '{job="nginx"} |= "error"')
            hours = int(p.get("hours", 1))
            log_entries = self._intrusion.query_loki(logql, hours)

        findings = self._intrusion.scan(log_entries)

        if findings["blocked_ips"] or findings["attack_patterns"]:
            self._critical_alert(
                "intrusion_detected",
                f"Blocked {len(findings['blocked_ips'])} IPs; "
                f"{len(findings['attack_patterns'])} attack patterns",
                findings,
            )

        return findings

    # ------------------------------------------------------------------
    # vulnerability_scan
    # ------------------------------------------------------------------

    def _handle_vuln_scan(self, p: dict[str, Any]) -> dict[str, Any]:
        repo_path = p.get("repo_path")
        repo_name = p.get("repo_name", repo_path or "unknown")

        if repo_path:
            return self._vuln.process_repo(repo_path, repo_name)

        return {"repos": self._vuln.scan_all_repos()}

    # ------------------------------------------------------------------
    # ssl_cert_monitor
    # ------------------------------------------------------------------

    def _handle_ssl(self, p: dict[str, Any]) -> dict[str, Any]:
        domain = p.get("domain")
        if domain:
            return self._ssl.check_domain(domain)
        return self._ssl.check_all()

    # ------------------------------------------------------------------
    # secrets_audit
    # ------------------------------------------------------------------

    def _handle_secrets(self, p: dict[str, Any]) -> dict[str, Any]:
        repo_path = p.get("repo_path")
        if repo_path:
            findings = self._secrets.scan_repo(repo_path)
            if findings:
                self._critical_alert(
                    "secrets_leak",
                    f"{len(findings)} potential secrets found in {repo_path}",
                    {"count": len(findings), "repo": repo_path},
                )
            return {"findings": findings, "total": len(findings)}

        return self._secrets.scan_all_repos()

    # ------------------------------------------------------------------
    # access_review
    # ------------------------------------------------------------------

    def _handle_access(self, p: dict[str, Any]) -> dict[str, Any]:
        service = p.get("service")
        if service:
            findings = self._access.review_service(service)
            flagged = self._access.flag_stale_keys(findings)
            return {"service": service, "accounts": findings, "flagged": flagged}

        return self._access.review_all()

    # ------------------------------------------------------------------
    # ddos_response
    # ------------------------------------------------------------------

    def _handle_ddos(self, p: dict[str, Any]) -> dict[str, Any]:
        zone_id = p.get("zone_id")
        result = self._ddos.respond(zone_id=zone_id)

        if result.get("attacks_detected", 0) > 0:
            self._critical_alert(
                "ddos_attack",
                f"DDoS detected on {result.get('zones_checked', 0)} zone(s)",
                result,
            )

        return result

    # ------------------------------------------------------------------
    # backup_integrity_check
    # ------------------------------------------------------------------

    def _handle_backup(self, p: dict[str, Any]) -> dict[str, Any]:
        result = self._backup.check()
        if not result["ok"]:
            self._critical_alert(
                "backup_stale",
                f"Backup integrity failure: {result.get('reason', '')}",
                result,
            )
        return result

    # ------------------------------------------------------------------
    # CRITICAL alert — bypasses task queue, publishes directly to Redis
    # ------------------------------------------------------------------

    def _critical_alert(
        self,
        event_type: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "agent": self.agent_name,
            "event_type": event_type,
            "severity": "CRITICAL",
            "message": message,
            "data": data or {},
        }
        try:
            self._redis.publish(SECURITY_ALERTS_CHANNEL, json.dumps(payload))
            logger.warning("security_critical_alert", event_type=event_type, message=message)
        except Exception as exc:
            logger.error("critical_alert_publish_failed", error=str(exc))


if __name__ == "__main__":
    config = AgentConfig.load("security")
    SecurityAgent("security", config).run()
