"""Postgres helpers for the backup agent."""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class BackupDB:

    def insert_log(
        self,
        *,
        backup_type: str,
        file_path: str,
        size_bytes: int,
        duration_seconds: float,
        verified: bool = False,
        error: str | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO backup_log
                        (backup_type, file_path, size_bytes, duration_seconds, verified, error)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (backup_type, file_path, size_bytes, duration_seconds, verified, error),
                )
                return str(cur.fetchone()[0])

    def get_last_backup(self, backup_type: str) -> dict | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM backup_log
                    WHERE backup_type = %s AND error IS NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (backup_type,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_recent_backups(self, backup_type: str, days: int = 7) -> list[dict]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM backup_log
                    WHERE backup_type = %s
                      AND error IS NULL
                      AND created_at >= NOW() - INTERVAL '%s days'
                    ORDER BY created_at DESC
                    """,
                    (backup_type, days),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_last_successful_timestamp(self) -> datetime | None:
        """Return the timestamp of the most recent successful backup of any type."""
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT MAX(created_at) FROM backup_log
                    WHERE error IS NULL
                      AND backup_type != 'restore_verify'
                    """
                )
                result = cur.fetchone()[0]
                if result is None:
                    return None
                if result.tzinfo is None:
                    result = result.replace(tzinfo=timezone.utc)
                return result
