"""
LaunchExecutor — polls for due launch tasks and dispatches them.

Marks completed/failed. Alerts immediately on critical task failure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.logger import get_logger

from .db import LaunchDB

logger = get_logger(__name__)


def dispatch_to_agent(
    agent: str,
    action: str,
    product: str,
    payload: dict,
) -> dict[str, Any]:
    from shared.queue.queue import TaskQueue
    queue = TaskQueue()
    queue.push(
        agent=agent,
        payload={"action": action, "product": product, **payload},
        priority=9,
    )
    return {"success": True, "agent": agent, "action": action}


def send_alert(
    product: str,
    agent: str,
    action: str,
    error: str,
    notify_email: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="support",
            payload={
                "action": "handle_ticket",
                "product": product,
                "user_id": "system",
                "channel": "internal",
                "subject": f"CRITICAL LAUNCH TASK FAILED — {agent}.{action}",
                "body": f"Error: {error}\nProduct: {product}",
                "user_email": notify_email,
                "classification": "BUG",
            },
            priority=10,
        )
    except Exception as exc:
        logger.error("launch_alert_failed", error=str(exc))


class LaunchExecutor:

    def __init__(self, db: LaunchDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self) -> dict[str, Any]:
        as_of = datetime.now(timezone.utc)
        due_tasks = self._db.list_pending_tasks(as_of=as_of)

        dispatched = 0
        failed = 0
        completed = 0
        notify_email = self._cfg.get("dutch_email", "dutch@vance.com")

        for task in due_tasks:
            plan_id = task["plan_id"]
            task_idx = task["task_idx"]
            agent = task["agent"]
            action = task["action"]
            product = task["product"]
            payload = task.get("payload", {})
            critical = task.get("critical", False)

            try:
                dispatch_to_agent(
                    agent=agent,
                    action=action,
                    product=product,
                    payload=payload,
                )
                self._db.update_task_status(plan_id=plan_id, task_idx=task_idx, status="completed")
                dispatched += 1
                completed += 1
                logger.info("launch_task_dispatched", agent=agent, action=action, product=product)
            except Exception as exc:
                self._db.update_task_status(plan_id=plan_id, task_idx=task_idx, status="failed")
                failed += 1
                logger.error("launch_task_failed", agent=agent, action=action, error=str(exc))
                if critical:
                    send_alert(
                        product=product,
                        agent=agent,
                        action=action,
                        error=str(exc),
                        notify_email=notify_email,
                    )

        return {
            "tasks_dispatched": dispatched,
            "tasks_failed": failed,
            "tasks_completed": completed,
        }
