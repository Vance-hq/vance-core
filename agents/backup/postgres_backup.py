"""Daily Postgres backup — dump, encrypt, upload to B2, apply retention."""

from __future__ import annotations

import subprocess
import tempfile
import time
from datetime import date, datetime, timedelta, timezone

from agents.integrations.connectors.backblaze import BackblazeConnector
from shared.config.settings import settings
from shared.logger import get_logger

from .db import BackupDB
from .encryptor import BackupEncryptor

logger = get_logger(__name__)

# Retention window maximums
DAILY_KEEP_DAYS = 7
WEEKLY_KEEP_WEEKS = 4
MONTHLY_KEEP_MONTHS = 12

_PREFIX = "backups/postgres"


class PostgresBackup:

    def __init__(self, cfg: dict, db: BackupDB | None = None) -> None:
        self._cfg = cfg
        self._db = db or BackupDB()
        self._storage = BackblazeConnector()
        key = cfg.get("encryption_key") or getattr(settings, "BACKUP_ENCRYPTION_KEY", "")
        self._enc = BackupEncryptor(key)
        self._db_url: str = cfg.get("database_url") or settings.DATABASE_URL

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict:
        """Dump, encrypt, upload, log, and prune old backups."""
        t0 = time.monotonic()
        today = date.today()
        db_name = self._parse_db_name(self._db_url)

        try:
            dump_bytes = self._pg_dump()
        except Exception as exc:
            self._db.insert_log(
                backup_type="postgres",
                file_path="",
                size_bytes=0,
                duration_seconds=round(time.monotonic() - t0, 2),
                error=str(exc),
            )
            raise

        encrypted = self._enc.encrypt(dump_bytes)
        size_bytes = len(encrypted)

        # Always write daily key
        daily_key = f"{_PREFIX}/daily/{today}_{db_name}.sql.gz.enc"
        self._storage.upload_file(encrypted, daily_key, "application/octet-stream")

        uploaded_keys = [daily_key]

        # Weekly key on Mondays (weekday == 0)
        if today.weekday() == 0:
            iso_week = today.isocalendar()
            weekly_key = f"{_PREFIX}/weekly/{iso_week.year}-W{iso_week.week:02d}_{db_name}.sql.gz.enc"
            self._storage.upload_file(encrypted, weekly_key, "application/octet-stream")
            uploaded_keys.append(weekly_key)

        # Monthly key on 1st of month
        if today.day == 1:
            monthly_key = f"{_PREFIX}/monthly/{today.strftime('%Y-%m')}_{db_name}.sql.gz.enc"
            self._storage.upload_file(encrypted, monthly_key, "application/octet-stream")
            uploaded_keys.append(monthly_key)

        duration = round(time.monotonic() - t0, 2)
        self._db.insert_log(
            backup_type="postgres",
            file_path=daily_key,
            size_bytes=size_bytes,
            duration_seconds=duration,
        )

        self._prune()

        return {
            "keys": uploaded_keys,
            "size_bytes": size_bytes,
            "duration_seconds": duration,
            "db_name": db_name,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _pg_dump(self) -> bytes:
        """Run pg_dump and return compressed bytes."""
        with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=True) as tmp:
            subprocess.run(
                ["pg_dump", "--format=custom", "--compress=9", "--no-owner",
                 "--no-privileges", f"--file={tmp.name}", self._db_url],
                capture_output=True,
                check=True,
                timeout=int(self._cfg.get("dump_timeout_s", 300)),
            )
            tmp.seek(0)
            return tmp.read()

    def _prune(self) -> None:
        """Delete backups outside retention windows."""
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
                        logger.info("backup_pruned", key=f["key"], tier=tier)
            except Exception as exc:
                logger.warning("prune_failed", tier=tier, error=str(exc))

    @staticmethod
    def _parse_db_name(db_url: str) -> str:
        """Extract database name from a postgres:// URL."""
        try:
            return db_url.rstrip("/").split("/")[-1].split("?")[0] or "vance"
        except Exception:
            return "vance"
