"""DB helpers for the deploy agent — pipeline_runs + shared deployments table."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class DeployDB:

    # ------------------------------------------------------------------
    # pipeline_runs
    # ------------------------------------------------------------------

    def save_pipeline_run(
        self,
        repo: str,
        status: str = "running",
        pr_number: int | None = None,
        branch: str | None = None,
        build_id: str | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO pipeline_runs
                        (id, repo, pr_number, branch, build_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (row_id, repo, pr_number, branch, build_id, status),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

    def update_pipeline_run(
        self,
        run_id: str,
        status: str,
        steps: list[dict[str, Any]] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pipeline_runs
                    SET status       = %s,
                        steps        = COALESCE(%s::jsonb, steps),
                        duration_ms  = COALESCE(%s, duration_ms),
                        completed_at = CASE WHEN %s IN ('success','failed','cancelled')
                                            THEN now() ELSE completed_at END
                    WHERE id = %s
                    """,
                    (
                        status,
                        psycopg2.extras.Json(steps) if steps is not None else None,
                        duration_ms,
                        status,
                        run_id,
                    ),
                )
                conn.commit()

    def get_pipeline_run(self, run_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM pipeline_runs WHERE id = %s", (run_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def get_latest_pipeline_run(
        self,
        repo: str,
        pr_number: int | None = None,
    ) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if pr_number is not None:
                    cur.execute(
                        """
                        SELECT * FROM pipeline_runs
                        WHERE repo = %s AND pr_number = %s
                        ORDER BY triggered_at DESC LIMIT 1
                        """,
                        (repo, pr_number),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM pipeline_runs
                        WHERE repo = %s
                        ORDER BY triggered_at DESC LIMIT 1
                        """,
                        (repo,),
                    )
                row = cur.fetchone()
                return dict(row) if row else None

    # ------------------------------------------------------------------
    # deployments (shared with dev agent)
    # ------------------------------------------------------------------

    def save_deployment(
        self,
        repo: str,
        environment: str,
        version: str,
        status: str,
        deployed_by_task_id: str = "",
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO deployments
                        (id, repo, environment, version, status, deployed_by_task_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (row_id, repo, environment, version, status, deployed_by_task_id),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

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
                    (status, deployed_at or datetime.now(timezone.utc), deployment_id),
                )
                conn.commit()

    def get_last_successful_deployment(
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
                    ORDER BY deployed_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    (repo, environment),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_previous_deployment(
        self,
        repo: str,
        environment: str,
        before_version: str,
    ) -> dict[str, Any] | None:
        """Return the most recent successful deployment before a given version."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM deployments
                    WHERE repo = %s AND environment = %s
                      AND status = 'success' AND version != %s
                    ORDER BY deployed_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    (repo, environment, before_version),
                )
                row = cur.fetchone()
                return dict(row) if row else None
