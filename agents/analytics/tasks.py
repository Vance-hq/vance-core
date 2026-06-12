"""Celery tasks for the analytics agent.

revenue_snapshot runs hourly (registered in shared/celery_app.py beat_schedule).
weekly_growth_report added here for optional weekly digest.
"""
from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

logger = get_logger(__name__)


def _enqueue(action: str, payload: dict | None = None) -> None:
    import uuid
    from datetime import datetime

    queue = TaskQueue()
    queue.push({
        "id": str(uuid.uuid4()),
        "agent": "analytics",
        "payload": {"action": action, **(payload or {})},
        "priority": 5,
        "created_at": datetime.utcnow().isoformat(),
    })


@app.task(name="agents.analytics.tasks.revenue_snapshot", bind=True, max_retries=3)
def revenue_snapshot(self) -> None:
    """Hourly Stripe revenue snapshot — stores MRR/ARR/churn to DB."""
    try:
        _enqueue("revenue_snapshot")
        logger.info("revenue_snapshot_enqueued")
    except Exception as exc:
        logger.error("revenue_snapshot_task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60)


@app.task(name="agents.analytics.tasks.weekly_growth_report", bind=True, max_retries=2)
def weekly_growth_report(self) -> None:
    """Weekly combined growth dashboard + product usage digest."""
    try:
        _enqueue("growth_dashboard", {"force_refresh": True})
        _enqueue("product_usage_report", {"days": 7})
        logger.info("weekly_growth_report_enqueued")
    except Exception as exc:
        logger.error("weekly_growth_report_task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=300)
