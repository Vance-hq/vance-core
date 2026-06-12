"""Celery tasks for the dev agent — weekly dependency updates, scheduled test runs."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.dev.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.dev.tasks.weekly_dependency_update", ignore_result=True)
def weekly_dependency_update() -> None:
    """Run weekly — update dependencies for all active repos."""
    from agents._base import AgentConfig
    from agents.dev.main import DevAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("dev")
    agent = DevAgent("dev", config)

    repos = list(config.custom.get("repos", {}).keys())
    for repo in repos:
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={"action": "dependency_update", "repo": repo},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("weekly_dep_update_failed", repo=repo, error=str(exc))


@app.task(name="agents.dev.tasks.daily_test_run", ignore_result=True)
def daily_test_run() -> None:
    """Run daily — execute unit tests for all repos."""
    from agents._base import AgentConfig
    from agents.dev.main import DevAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("dev")
    agent = DevAgent("dev", config)

    repos = list(config.custom.get("repos", {}).keys())
    for repo in repos:
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={"action": "run_tests", "repo": repo, "test_type": "unit"},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("daily_test_run_failed", repo=repo, error=str(exc))
