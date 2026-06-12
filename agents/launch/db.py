"""
Launch DB — launch_plans and launch_results tables.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class LaunchDB:

    # ------------------------------------------------------------------
    # launch_plans
    # ------------------------------------------------------------------

    def save_plan(
        self,
        product: str,
        launch_type: str,
        launch_date: date,
        tasks: list[dict],
        status: str = "planned",
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO launch_plans
                        (product, launch_type, launch_date, status, tasks)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (product, launch_type, launch_date, status, json.dumps(tasks)),
                )
                row = cur.fetchone()
        return str(row["id"])

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM launch_plans WHERE id = %s",
                    (plan_id,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def list_pending_tasks(
        self,
        as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Returns flattened due task rows — each dict has plan metadata + task fields.
        A task is due when launch_date + offset_days <= as_of date and status = 'pending'.
        """
        as_of = as_of or datetime.now(timezone.utc)
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        lp.id            AS plan_id,
                        lp.product,
                        lp.launch_date,
                        lp.tasks,
                        lp.status        AS plan_status
                    FROM launch_plans lp
                    WHERE lp.status IN ('planned', 'in_progress')
                    """,
                )
                plans = [dict(r) for r in cur.fetchall()]

        due: list[dict[str, Any]] = []
        for plan in plans:
            launch_date = date.fromisoformat(str(plan["launch_date"]))
            tasks = json.loads(plan["tasks"]) if isinstance(plan["tasks"], str) else plan["tasks"]
            for idx, task in enumerate(tasks):
                if task.get("status") != "pending":
                    continue
                task_date = date.fromordinal(
                    launch_date.toordinal() + int(task.get("offset_days", 0))
                )
                if task_date <= as_of.date():
                    due.append({
                        "plan_id": plan["plan_id"],
                        "task_idx": idx,
                        "product": plan["product"],
                        "agent": task.get("agent", ""),
                        "action": task.get("action", ""),
                        "payload": task.get("payload", {}),
                        "critical": task.get("critical", False),
                    })
        return due

    def update_task_status(
        self,
        plan_id: str,
        task_idx: int,
        status: str,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE launch_plans
                    SET tasks = jsonb_set(
                        tasks::jsonb,
                        ARRAY[%s::text, 'status'],
                        to_jsonb(%s::text)
                    )
                    WHERE id = %s
                    """,
                    (str(task_idx), status, plan_id),
                )

    def update_plan_status(self, plan_id: str, status: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE launch_plans SET status = %s WHERE id = %s",
                    (status, plan_id),
                )

    # ------------------------------------------------------------------
    # launch_results
    # ------------------------------------------------------------------

    def save_result(
        self,
        launch_id: str,
        metric: str,
        value: str,
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO launch_results (launch_id, metric, value)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (launch_id, metric, value),
                )
                row = cur.fetchone()
        return str(row["id"])

    def get_results(self, launch_id: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM launch_results WHERE launch_id = %s ORDER BY recorded_at",
                    (launch_id,),
                )
                return [dict(r) for r in cur.fetchall()]
