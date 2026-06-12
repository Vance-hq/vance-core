"""Celery tasks for the finance agent."""

from __future__ import annotations

from shared.celery_app import app


@app.task(name="agents.finance.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass
