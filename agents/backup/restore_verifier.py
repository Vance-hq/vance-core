"""Weekly restore verification — randomly restores a backup to a test schema."""

from __future__ import annotations

import random
import subprocess
import tempfile
import time

from agents.integrations.connectors.backblaze import BackblazeConnector
from shared.config.settings import settings
from shared.db.client import get_db
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import BackupDB
from .encryptor import BackupEncryptor

logger = get_logger(__name__)

TEST_SCHEMA = "backup_test"
_PREFIX = "backups/postgres/daily"

# Expected minimum row counts for validation; configurable via config
_DEFAULT_MIN_COUNTS: dict[str, int] = {
    "tasks": 0,
    "analytics_snapshots": 0,
}


class RestoreVerifier:

    def __init__(self, cfg: dict, db: BackupDB | None = None) -> None:
        self._cfg = cfg
        self._db = db or BackupDB()
        self._storage = BackblazeConnector()
        key = cfg.get("encryption_key") or getattr(settings, "BACKUP_ENCRYPTION_KEY", "")
        self._enc = BackupEncryptor(key)
        self._db_url: str = cfg.get("database_url") or settings.DATABASE_URL
        self._min_counts: dict[str, int] = cfg.get("restore_min_counts", _DEFAULT_MIN_COUNTS)
        self._test_schema: str = cfg.get("test_schema", TEST_SCHEMA)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(self) -> dict:
        t0 = time.monotonic()

        # Pick a random backup from the last 7 days
        recent = self._db.get_recent_backups("postgres", days=7)
        if not recent:
            return self._log_result(
                success=False,
                key="",
                duration=time.monotonic() - t0,
                reason="no_recent_backups",
            )

        target = random.choice(recent)
        key = target["file_path"]
        logger.info("restore_verify_selected", key=key)

        try:
            encrypted = self._storage.download_file(key)["data"]
            dump_bytes = self._enc.decrypt(encrypted)
            self._restore_to_test_schema(dump_bytes)
            ok, counts = self._validate()
        except Exception as exc:
            result = self._log_result(
                success=False,
                key=key,
                duration=time.monotonic() - t0,
                reason=str(exc),
            )
            self._alert_failure(key, str(exc))
            return result

        if not ok:
            reason = f"row count validation failed: {counts}"
            result = self._log_result(
                success=False,
                key=key,
                duration=time.monotonic() - t0,
                reason=reason,
            )
            self._alert_failure(key, reason)
            return result

        return self._log_result(
            success=True,
            key=key,
            duration=time.monotonic() - t0,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _restore_to_test_schema(self, dump_bytes: bytes) -> None:
        """Write dump to temp file, drop+recreate test schema, restore."""
        with tempfile.NamedTemporaryFile(suffix=".dump", delete=True) as tmp:
            tmp.write(dump_bytes)
            tmp.flush()

            # Drop and recreate the test schema
            with get_db() as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(f'DROP SCHEMA IF EXISTS "{self._test_schema}" CASCADE')
                    cur.execute(f'CREATE SCHEMA "{self._test_schema}"')

            # Restore into test schema using pg_restore
            subprocess.run(
                [
                    "pg_restore",
                    "--no-owner",
                    "--no-privileges",
                    f"--schema={self._test_schema}",
                    f"--dbname={self._db_url}",
                    tmp.name,
                ],
                capture_output=True,
                check=False,  # pg_restore exits non-zero on warnings; don't fail on those
                timeout=int(self._cfg.get("restore_timeout_s", 300)),
            )

    def _validate(self) -> tuple[bool, dict]:
        """Run row count checks against the restored test schema."""
        counts: dict[str, int] = {}
        ok = True

        with get_db() as conn:
            with conn.cursor() as cur:
                for table, min_count in self._min_counts.items():
                    try:
                        cur.execute(
                            f'SELECT COUNT(*) FROM "{self._test_schema}"."{table}"'
                        )
                        count = cur.fetchone()[0]
                        counts[table] = count
                        if count < min_count:
                            ok = False
                            logger.warning(
                                "restore_row_count_low",
                                table=table,
                                count=count,
                                min=min_count,
                            )
                    except Exception as exc:
                        logger.warning("restore_validate_query_failed", table=table, error=str(exc))
                        counts[table] = -1
                        ok = False

        return ok, counts

    def _alert_failure(self, key: str, reason: str) -> None:
        logger.error("restore_verify_failed", key=key, reason=reason)
        payload = {
            "action": "backup_restore_failed",
            "backup_key": key,
            "reason": reason,
        }
        TaskQueue().push(agent="security", payload=payload, priority=1)
        TaskQueue().push(agent="reporting", payload=payload, priority=2)

    def _log_result(
        self,
        *,
        success: bool,
        key: str,
        duration: float,
        reason: str | None = None,
    ) -> dict:
        self._db.insert_log(
            backup_type="restore_verify",
            file_path=key,
            size_bytes=0,
            duration_seconds=round(duration, 2),
            verified=success,
            error=reason,
        )
        result: dict = {"success": success, "backup_key": key, "duration_seconds": round(duration, 2)}
        if reason:
            result["reason"] = reason
        return result
