"""Celery tasks for the strategy agent."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.strategy.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.strategy.tasks.daily_synthesize_signals", ignore_result=True)
def daily_synthesize_signals() -> None:
    """Run daily after reporting brief — synthesize all agent signals into one strategic insight."""
    import uuid

    from agents._base import AgentConfig
    from agents.strategy.main import StrategyAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("strategy")
    agent = StrategyAgent("strategy", config)
    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.STRATEGY,
        payload={"action": "synthesize_signals"},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("daily_synthesize_signals_failed", error=str(exc))


@app.task(name="agents.strategy.tasks.daily_recommend_next_action", ignore_result=True)
def daily_recommend_next_action() -> None:
    """Run daily — generate 3 prioritized recommendations; auto-execute high-confidence ones."""
    import uuid

    from agents._base import AgentConfig
    from agents.strategy.main import StrategyAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("strategy")
    agent = StrategyAgent("strategy", config)
    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.STRATEGY,
        payload={"action": "recommend_next_action"},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("daily_recommend_next_action_failed", error=str(exc))


@app.task(name="agents.strategy.tasks.weekly_product_prioritization", ignore_result=True)
def weekly_product_prioritization() -> None:
    """Run weekly — score products and deliver resource allocation recommendation."""
    import uuid

    from agents._base import AgentConfig
    from agents.strategy.main import StrategyAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("strategy")
    agent = StrategyAgent("strategy", config)
    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.STRATEGY,
        payload={"action": "product_prioritization"},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("weekly_product_prioritization_failed", error=str(exc))


@app.task(name="agents.strategy.tasks.weekly_pivot_detection", ignore_result=True)
def weekly_pivot_detection() -> None:
    """Run weekly — check each product for pivot triggers."""
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
            payload={"action": "pivot_detection", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("weekly_pivot_detection_failed", product=product, error=str(exc))


@app.task(name="agents.strategy.tasks.weekly_growth_analysis", ignore_result=True)
def weekly_growth_analysis() -> None:
    """Run weekly — analyze growth levers per product (legacy)."""
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
