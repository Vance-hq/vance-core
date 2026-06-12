"""Daily backup of user files, logs, and config — compress, encrypt, upload."""

from __future__ import annotations

import io
import os
import tarfile
import time
from datetime import date, datetime, timedelta, timezone

from agents.integrations.connectors.backblaze import BackblazeConnector
from shared.config.settings import settings
from shared.logger import get_logger

from .db import BackupDB
from .encryptor import BackupEncryptor

logger = get_logger(__name__)

DAILY_KEEP_DAYS = 7
WEEKLY_KEEP_WEEKS = 4
MONTHLY_KEEP_MONTHS = 12

_PREFIX = "backups/files"
_LOG_MAX_AGE_DAYS = 30


class FileBackup:
    """Compress /app/uploads, /app/config, and recent /app/logs, then encrypt + upload."""

    def __init__(self, cfg: dict, db: BackupDB | None = None) -> None:
        self._cfg = cfg
        self._db = db or BackupDB()
        self._storage = BackblazeConnector()
        key = cfg.get("encryption_key") or getattr(settings, "BACKUP_ENCRYPTION_KEY", "")
        self._enc = BackupEncryptor(key)
        self._paths: list[str] = cfg.get("backup_paths", ["/app/uploads", "/app/config"])
        self._log_path: str = cfg.get("log_path", "/app/logs")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict:
        t0 = time.monotonic()
        today = date.today()

        try:
            archive_bytes = self._create_archive()
        except Exception as exc:
            self._db.insert_log(
                backup_type="files",
                file_path="",
                size_bytes=0,
                duration_seconds=round(time.monotonic() - t0, 2),
                error=str(exc),
            )
            raise

        encrypted = self._enc.encrypt(archive_bytes)
        size_bytes = len(encrypted)

        daily_key = f"{_PREFIX}/daily/{today}_files.tar.gz.enc"
        self._storage.upload_file(encrypted, daily_key, "application/octet-stream")
        uploaded_keys = [daily_key]

        if today.weekday() == 0:
            iso_week = today.isocalendar()
            weekly_key = f"{_PREFIX}/weekly/{iso_week.year}-W{iso_week.week:02d}_files.tar.gz.enc"
            self._storage.upload_file(encrypted, weekly_key, "application/octet-stream")
            uploaded_keys.append(weekly_key)

        if today.day == 1:
            monthly_key = f"{_PREFIX}/monthly/{today.strftime('%Y-%m')}_files.tar.gz.enc"
            self._storage.upload_file(encrypted, monthly_key, "application/octet-stream")
            uploaded_keys.append(monthly_key)

        duration = round(time.monotonic() - t0, 2)
        self._db.insert_log(
            backup_type="files",
            file_path=daily_key,
            size_bytes=size_bytes,
            duration_seconds=duration,
        )

        self._prune()

        return {
            "keys": uploaded_keys,
            "size_bytes": size_bytes,
            "duration_seconds": duration,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _create_archive(self) -> bytes:
        """Build an in-memory .tar.gz of all configured paths + recent logs."""
        buf = io.BytesIO()
        log_cutoff = datetime.now(timezone.utc) - timedelta(days=_LOG_MAX_AGE_DAYS)

        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for path in self._paths:
                if os.path.exists(path):
                    tar.add(path, recursive=True)

            # Logs: only files modified within the last 30 days
            if os.path.isdir(self._log_path):
                for root, _, files in os.walk(self._log_path):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        try:
                            mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)
                            if mtime >= log_cutoff:
                                tar.add(fpath)
                        except OSError:
                            pass

        return buf.getvalue()

    def _prune(self) -> None:
        now = datetime.now(timezone.utc)
        cutoffs = {
            "daily": now - timedelta(days=DAILY_KEEP_DAYS),
            "weekly": now - timedelta(weeks=WEEKLY_KEEP_WEEKS),
            "monthly": now - timedelta(days=MONTHLY_KEEP_MONTHS * 30),
        }
        for tier, cutoff in cutoffs.items():
            try:
                files = self._storage.list_files(prefix=f"{_PREFIX}/{tier}/")
                for f in files:
                    last_mod = datetime.fromisoformat(f["last_modified"])
                    if last_mod.tzinfo is None:
                        last_mod = last_mod.replace(tzinfo=timezone.utc)
                    if last_mod < cutoff:
                        self._storage.delete_file(f["key"])
                        logger.info("file_backup_pruned", key=f["key"], tier=tier)
            except Exception as exc:
                logger.warning("file_prune_failed", tier=tier, error=str(exc))
