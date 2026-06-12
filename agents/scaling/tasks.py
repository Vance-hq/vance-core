"""Celery scheduled tasks for the scaling agent."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


def _agent():
    from agents._base import AgentConfig
    from agents.scaling.main import ScalingAgent

    config = AgentConfig.load("scaling")
    return ScalingAgent("scaling", config)


def _task(action: str, **payload):
    import uuid
    from shared.types import AgentCapability, Task

    return Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.SCALING,
        payload={"action": action, **payload},
    )


@app.task(name="agents.scaling.tasks.collect_resources", ignore_result=True)
def collect_resources() -> None:
    """Run every 60 seconds — collect CPU, memory, disk, container stats."""
    try:
        _agent().handle(_task("resource_monitor"))
    except Exception as exc:
        logger.error("collect_resources_failed", error=str(exc))


@app.task(name="agents.scaling.tasks.check_thresholds", ignore_result=True)
def check_thresholds() -> None:
    """Run every 60 seconds — evaluate current metrics against alert thresholds."""
    try:
        _agent().handle(_task("alert_threshold"))
    except Exception as exc:
        logger.error("check_thresholds_failed", error=str(exc))


@app.task(name="agents.scaling.tasks.monthly_capacity_plan", ignore_result=True)
def monthly_capacity_plan() -> None:
    """Run monthly — trend analysis and 90-day hardware limit projection."""
    try:
        _agent().handle(_task("capacity_plan"))
    except Exception as exc:
        logger.error("monthly_capacity_plan_failed", error=str(exc))


@app.task(name="agents.scaling.tasks.remediate_resource", ignore_result=True)
def remediate_resource(trigger: str, value: float) -> None:
    """Triggered by threshold checker on CRITICAL alerts."""
    try:
        _agent().handle(_task("auto_remediate", trigger=trigger, value=value))
    except Exception as exc:
        logger.error("remediate_resource_failed", trigger=trigger, error=str(exc))
