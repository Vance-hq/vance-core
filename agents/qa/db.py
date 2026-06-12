"""
QA DB — test_runs and bugs tables.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class QaDB:

    # ------------------------------------------------------------------
    # test_runs
    # ------------------------------------------------------------------

    def save_test_run(
        self,
        repo: str,
        run_type: str,
        passed: int,
        failed: int,
        coverage_pct: float,
        duration_ms: int,
        triggered_by: str = "",
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO test_runs
                        (repo, run_type, passed, failed, coverage_pct, duration_ms, triggered_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (repo, run_type, passed, failed, coverage_pct, duration_ms, triggered_by),
                )
                return str(cur.fetchone()["id"])

    def get_recent_runs(
        self,
        repo: str,
        run_type: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if run_type:
                    cur.execute(
                        """
                        SELECT * FROM test_runs
                        WHERE repo = %s AND run_type = %s
                        ORDER BY run_at DESC
                        LIMIT %s
                        """,
                        (repo, run_type, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM test_runs
                        WHERE repo = %s
                        ORDER BY run_at DESC
                        LIMIT %s
                        """,
                        (repo, limit),
                    )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # bugs
    # ------------------------------------------------------------------

    def save_bug(
        self,
        product: str,
        severity: str,
        title: str,
        stack_trace: str,
        affected_users: int,
        status: str = "open",
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO bugs
                        (product, severity, title, stack_trace, affected_users, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (product, severity, title, stack_trace, affected_users, status),
                )
                return str(cur.fetchone()["id"])

    def update_bug(
        self,
        bug_id: str,
        status: str,
        resolved_at: datetime | None = None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE bugs
                    SET status = %s,
                        resolved_at = COALESCE(%s, resolved_at)
                    WHERE id = %s
                    """,
                    (status, resolved_at, bug_id),
                )

    def get_open_bugs(
        self,
        product: str,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if severity:
                    cur.execute(
                        """
                        SELECT * FROM bugs
                        WHERE product = %s AND status = 'open' AND severity = %s
                        ORDER BY created_at DESC
                        """,
                        (product, severity),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM bugs
                        WHERE product = %s AND status = 'open'
                        ORDER BY created_at DESC
                        """,
                        (product,),
                    )
                return [dict(r) for r in cur.fetchall()]
