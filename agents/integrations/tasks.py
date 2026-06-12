"""Celery tasks for the integrations agent."""

from __future__ import annotations

from shared.celery_app import app


@app.task(name="agents.integrations.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass
