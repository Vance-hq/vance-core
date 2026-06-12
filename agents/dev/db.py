"""
Dev DB — deployments and build_log tables.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class DevDB:

    # ------------------------------------------------------------------
    # deployments
    # ------------------------------------------------------------------

    def save_deployment(
        self,
        repo: str,
        environment: str,
        version: str,
        status: str,
        deployed_by_task_id: str,
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO deployments
                        (repo, environment, version, status, deployed_by_task_id)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (repo, environment, version, status, deployed_by_task_id),
                )
                return str(cur.fetchone()["id"])

    def update_deployment(
        self,
        deployment_id: str,
        status: str,
        deployed_at: datetime | None = None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE deployments
                    SET status = %s,
                        deployed_at = COALESCE(%s, deployed_at)
                    WHERE id = %s
                    """,
                    (status, deployed_at, deployment_id),
                )

    def get_recent_deployments(
        self,
        repo: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM deployments
                    WHERE repo = %s
                    ORDER BY deployed_at DESC NULLS LAST
                    LIMIT %s
                    """,
                    (repo, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_last_deployment(
        self,
        repo: str,
        environment: str,
    ) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM deployments
                    WHERE repo = %s AND environment = %s AND status = 'success'
                    ORDER BY deployed_at DESC
                    LIMIT 1
                    """,
                    (repo, environment),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # build_log
    # ------------------------------------------------------------------

    def save_build_log(
        self,
        repo: str,
        task_type: str,
        success: bool,
        duration_seconds: float,
        issue_number: int | None = None,
        error_msg: str | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO build_log
                        (repo, task_type, issue_number, success, duration_seconds, error_msg)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (repo, task_type, issue_number, success, duration_seconds, error_msg),
                )
                return str(cur.fetchone()["id"])

    def get_build_logs(
        self,
        repo: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM build_log
                    WHERE repo = %s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (repo, limit),
                )
                return [dict(r) for r in cur.fetchall()]
