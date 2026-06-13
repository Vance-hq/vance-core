"""Celery tasks for the reporting agent."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.reporting.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.reporting.tasks.daily_brief", ignore_result=True)
def daily_brief() -> None:
    """Run every morning — compile and deliver the daily briefing via voice and email."""
    import uuid

    from agents._base import AgentConfig
    from agents.reporting.main import ReportingAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("reporting")
    agent = ReportingAgent("reporting", config)
    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.REPORTING,
        payload={"action": "daily_brief"},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("daily_brief_task_failed", error=str(exc))


@app.task(name="agents.reporting.tasks.weekly_summary", ignore_result=True)
def weekly_summary() -> None:
    """Run every Sunday evening — compile week-over-week summary with trend analysis."""
    import uuid

    from agents._base import AgentConfig
    from agents.reporting.main import ReportingAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("reporting")
    agent = ReportingAgent("reporting", config)
    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.REPORTING,
        payload={"action": "weekly_summary"},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("weekly_summary_task_failed", error=str(exc))


@app.task(name="agents.reporting.tasks.weekly_digest", ignore_result=True)
def weekly_digest() -> None:
    """Legacy — kept for backward compat. Prefer weekly_summary."""
    import uuid

    from agents._base import AgentConfig
    from agents.reporting.main import ReportingAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("reporting")
    agent = ReportingAgent("reporting", config)
    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.REPORTING,
        payload={"action": "weekly_digest"},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("weekly_digest_task_failed", error=str(exc))
