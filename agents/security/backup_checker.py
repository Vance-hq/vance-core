"""Backup integrity checker — confirms backup agent ran within the last 25 hours."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from shared.logger import get_logger

from .db import SecurityDB

logger = get_logger(__name__)

BACKUP_MAX_AGE_HOURS = 25


class BackupChecker:

    def __init__(self, db: SecurityDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._max_age_hours: int = int(cfg.get("backup_max_age_hours", BACKUP_MAX_AGE_HOURS))

    # ------------------------------------------------------------------

    def check(self) -> dict[str, Any]:
        """
        Confirm last successful backup is within the allowed window.
        Returns {'ok': bool, 'last_backup': str|None, 'age_hours': float|None}.
        """
        last_backup = self._db.get_last_backup_timestamp()

        if last_backup is None:
            return {
                "ok": False,
                "last_backup": None,
                "age_hours": None,
                "reason": "no backup record found",
            }

        now = datetime.now(timezone.utc)
        if last_backup.tzinfo is None:
            last_backup = last_backup.replace(tzinfo=timezone.utc)

        age = now - last_backup
        age_hours = age.total_seconds() / 3600

        ok = age_hours < self._max_age_hours
        result = {
            "ok": ok,
            "last_backup": last_backup.isoformat(),
            "age_hours": round(age_hours, 2),
            "threshold_hours": self._max_age_hours,
        }

        if not ok:
            logger.error(
                "backup_stale",
                age_hours=age_hours,
                threshold=self._max_age_hours,
                last_backup=last_backup.isoformat(),
            )
            result["reason"] = f"last backup is {age_hours:.1f}h old (threshold: {self._max_age_hours}h)"

        return result
