"""Celery scheduled tasks for the backup agent."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


def _agent():
    from agents._base import AgentConfig
    from agents.backup.main import BackupAgent

    config = AgentConfig.load("backup")
    return BackupAgent("backup", config)


def _task(action: str, **payload):
    import uuid
    from shared.types import AgentCapability, Task

    return Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.BACKUP,
        payload={"action": action, **payload},
    )


@app.task(name="agents.backup.tasks.daily_postgres_backup", ignore_result=True)
def daily_postgres_backup() -> None:
    """Run daily — full Postgres dump, encrypt, upload to B2."""
    try:
        _agent().handle(_task("backup_postgres"))
    except Exception as exc:
        logger.error("daily_postgres_backup_failed", error=str(exc))


@app.task(name="agents.backup.tasks.daily_file_backup", ignore_result=True)
def daily_file_backup() -> None:
    """Run daily — archive /app/uploads, /app/config, recent /app/logs."""
    try:
        _agent().handle(_task("backup_files"))
    except Exception as exc:
        logger.error("daily_file_backup_failed", error=str(exc))


@app.task(name="agents.backup.tasks.weekly_restore_verify", ignore_result=True)
def weekly_restore_verify() -> None:
    """Run weekly — restore a random recent backup to test schema and validate."""
    try:
        _agent().handle(_task("verify_restore"))
    except Exception as exc:
        logger.error("weekly_restore_verify_failed", error=str(exc))


@app.task(name="agents.backup.tasks.weekly_mailcow_backup", ignore_result=True)
def weekly_mailcow_backup() -> None:
    """Run weekly — export Mailcow domain/mailbox/alias config and encrypt to B2."""
    try:
        _agent().handle(_task("mailcow_backup"))
    except Exception as exc:
        logger.error("weekly_mailcow_backup_failed", error=str(exc))
