"""Celery tasks for the reporting agent."""

from __future__ import annotations

from shared.celery_app import app


@app.task(name="agents.reporting.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass
