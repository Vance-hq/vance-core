"""Backup agent — Postgres, files, Mailcow, and weekly restore verification."""

from __future__ import annotations

from agents._base import BaseAgent, AgentConfig
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .db import BackupDB
from .file_backup import FileBackup
from .mailcow_backup import MailcowBackup
from .postgres_backup import PostgresBackup
from .restore_verifier import RestoreVerifier

logger = get_logger(__name__)


class BackupAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom or {}

        self._db = BackupDB()
        self._pg = PostgresBackup(cfg, self._db)
        self._files = FileBackup(cfg, self._db)
        self._mailcow = MailcowBackup(cfg, self._db)
        self._verifier = RestoreVerifier(cfg, self._db)

        self._dispatch = {
            "backup_postgres": self._backup_postgres,
            "backup_files": self._backup_files,
            "verify_restore": self._verify_restore,
            "mailcow_backup": self._mailcow_backup,
        }

    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        logger.info("backup_task_received", action=action, task_id=task.id)

        handler = self._dispatch.get(action)
        if not handler:
            return TaskResult(task_id=task.id, success=False, error=f"unknown action: {action}")

        try:
            output = handler(task.payload)
            return TaskResult(task_id=task.id, success=True, output=output)
        except Exception as exc:
            logger.error("backup_task_failed", action=action, error=str(exc))
            return TaskResult(task_id=task.id, success=False, error=str(exc))

    def health_check(self) -> bool:
        try:
            self._db.get_last_backup("postgres")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _backup_postgres(self, payload: dict) -> dict:
        return self._pg.run()

    def _backup_files(self, payload: dict) -> dict:
        return self._files.run()

    def _verify_restore(self, payload: dict) -> dict:
        return self._verifier.verify()

    def _mailcow_backup(self, payload: dict) -> dict:
        return self._mailcow.run()


if __name__ == "__main__":
    config = AgentConfig.load("backup")
    BackupAgent("backup", config).run()
