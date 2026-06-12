"""Celery tasks for the ads agent."""

from __future__ import annotations

from shared.celery_app import app


@app.task(name="agents.ads.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass
