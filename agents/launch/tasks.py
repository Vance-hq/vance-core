"""Celery tasks for the launch agent — hourly executor poll."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.launch.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.launch.tasks.hourly_execute_launch", ignore_result=True)
def hourly_execute_launch() -> None:
    """Run hourly — dispatch any launch tasks that are now due."""
    import uuid

    from agents._base import AgentConfig
    from agents.launch.main import LaunchAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("launch")
    agent = LaunchAgent("launch", config)
    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.MARKETING,
        payload={"action": "execute_launch"},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("hourly_execute_launch_failed", error=str(exc))
