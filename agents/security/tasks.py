"""Celery scheduled tasks for the security agent."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


def _agent():
    from agents._base import AgentConfig
    from agents.security.main import SecurityAgent

    config = AgentConfig.load("security")
    return SecurityAgent("security", config)


def _task(action: str, **payload):
    import uuid
    from shared.types import AgentCapability, Task

    return Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.SECURITY,
        payload={"action": action, **payload},
    )


@app.task(name="agents.security.tasks.uptime_check", ignore_result=True)
def uptime_check() -> None:
    """Run every 60 seconds — check all service uptime."""
    try:
        _agent().handle(_task("uptime_monitor"))
    except Exception as exc:
        logger.error("uptime_check_failed", error=str(exc))


@app.task(name="agents.security.tasks.intrusion_scan", ignore_result=True)
def intrusion_scan() -> None:
    """Run every 5 minutes — scan Nginx and auth logs for attacks."""
    try:
        _agent().handle(_task("intrusion_detect"))
    except Exception as exc:
        logger.error("intrusion_scan_failed", error=str(exc))


@app.task(name="agents.security.tasks.ddos_monitor", ignore_result=True)
def ddos_monitor() -> None:
    """Run every 5 minutes — check Cloudflare analytics for traffic spikes."""
    try:
        _agent().handle(_task("ddos_response"))
    except Exception as exc:
        logger.error("ddos_monitor_failed", error=str(exc))


@app.task(name="agents.security.tasks.daily_ssl_check", ignore_result=True)
def daily_ssl_check() -> None:
    """Run daily — check SSL cert expiry for all configured domains."""
    try:
        _agent().handle(_task("ssl_cert_monitor"))
    except Exception as exc:
        logger.error("daily_ssl_check_failed", error=str(exc))


@app.task(name="agents.security.tasks.daily_backup_check", ignore_result=True)
def daily_backup_check() -> None:
    """Run daily — confirm backup agent ran within the last 25 hours."""
    try:
        _agent().handle(_task("backup_integrity_check"))
    except Exception as exc:
        logger.error("daily_backup_check_failed", error=str(exc))


@app.task(name="agents.security.tasks.weekly_vuln_scan", ignore_result=True)
def weekly_vuln_scan() -> None:
    """Run weekly — scan all repos for CVEs."""
    try:
        _agent().handle(_task("vulnerability_scan"))
    except Exception as exc:
        logger.error("weekly_vuln_scan_failed", error=str(exc))


@app.task(name="agents.security.tasks.weekly_secrets_audit", ignore_result=True)
def weekly_secrets_audit() -> None:
    """Run weekly — scan all git history for leaked credentials."""
    try:
        _agent().handle(_task("secrets_audit"))
    except Exception as exc:
        logger.error("weekly_secrets_audit_failed", error=str(exc))


@app.task(name="agents.security.tasks.monthly_access_review", ignore_result=True)
def monthly_access_review() -> None:
    """Run monthly — audit GitHub / Vercel / Cloudflare access."""
    try:
        _agent().handle(_task("access_review"))
    except Exception as exc:
        logger.error("monthly_access_review_failed", error=str(exc))
