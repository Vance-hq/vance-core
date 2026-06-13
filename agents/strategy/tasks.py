"""Celery tasks for the strategy agent — weekly and quarterly schedules."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.strategy.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.strategy.tasks.weekly_growth_analysis", ignore_result=True)
def weekly_growth_analysis() -> None:
    """Run weekly — analyze growth levers per product."""
    import uuid

    from agents._base import AgentConfig
    from agents.strategy.main import StrategyAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("strategy")
    agent = StrategyAgent("strategy", config)

    for product in config.custom.get("products", ["starpio", "oneserv", "localoutrank"]):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.STRATEGY,
            payload={"action": "analyze_growth_levers", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("weekly_growth_analysis_failed", product=product, error=str(exc))
