"""Celery scheduled tasks for the deploy agent."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


def _agent():
    from agents._base import AgentConfig
    from agents.deploy.main import DeployAgent

    config = AgentConfig.load("deploy")
    return DeployAgent("deploy", config)


def _task(action: str, **payload):
    import uuid
    from shared.types import AgentCapability, Task

    return Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.DEPLOY,
        payload={"action": action, **payload},
    )


@app.task(name="agents.deploy.tasks.weekly_environment_sync", ignore_result=True)
def weekly_environment_sync() -> None:
    """Run weekly — sync DB schema from production to staging for all repos."""
    from agents._base import AgentConfig

    try:
        config = AgentConfig.load("deploy")
        repos = list(config.custom.get("repos", {}).keys())
        agent = _agent()
        for repo in repos:
            try:
                agent.handle(_task("environment_sync", repo=repo))
            except Exception as exc:
                logger.error("env_sync_repo_failed", repo=repo, error=str(exc))
    except Exception as exc:
        logger.error("weekly_environment_sync_failed", error=str(exc))


@app.task(name="agents.deploy.tasks.ci_pipeline_task", ignore_result=True)
def ci_pipeline_task(repo: str, pr_number: int, branch: str, build_id: str = "") -> None:
    """Triggered by GitHub webhook on PR open/update."""
    try:
        _agent().handle(_task("ci_pipeline", repo=repo, pr_number=pr_number, branch=branch, build_id=build_id))
    except Exception as exc:
        logger.error("ci_pipeline_task_failed", repo=repo, pr=pr_number, error=str(exc))


@app.task(name="agents.deploy.tasks.promote_to_production_task", ignore_result=True)
def promote_to_production_task(repo: str, build_id: str, task_id: str = "") -> None:
    """Triggered after CI passes and QA approves."""
    try:
        _agent().handle(_task("promote_to_production", repo=repo, build_id=build_id, task_id=task_id))
    except Exception as exc:
        logger.error("promote_task_failed", repo=repo, build_id=build_id, error=str(exc))


@app.task(name="agents.deploy.tasks.rollback_task", ignore_result=True)
def rollback_task(repo: str, reason: str = "qa_regression", affected_users: int = 0) -> None:
    """Triggered by QA regression failure or voice command."""
    try:
        _agent().handle(_task("rollback", repo=repo, reason=reason, affected_users=affected_users))
    except Exception as exc:
        logger.error("rollback_task_failed", repo=repo, error=str(exc))
