"""Celery tasks for the research agent — weekly/daily/monthly/quarterly schedules."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.research.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.research.tasks.daily_market_signal_scan", ignore_result=True)
def daily_market_signal_scan() -> None:
    """Run daily — scan industry signals for all products."""
    import uuid

    from agents._base import AgentConfig
    from agents.research.main import ResearchAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("research")
    agent = ResearchAgent("research", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "market_signal_scan", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("daily_signal_scan_failed", product=product, error=str(exc))


@app.task(name="agents.research.tasks.weekly_competitor_monitor", ignore_result=True)
def weekly_competitor_monitor() -> None:
    """Run weekly — deep-scan all competitors per product."""
    import uuid

    from agents._base import AgentConfig
    from agents.research.main import ResearchAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("research")
    agent = ResearchAgent("research", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "competitor_monitor", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("weekly_competitor_monitor_failed", product=product, error=str(exc))


@app.task(name="agents.research.tasks.monthly_customer_sentiment", ignore_result=True)
def monthly_customer_sentiment() -> None:
    """Run monthly — batch sentiment analysis per product."""
    import uuid

    from agents._base import AgentConfig
    from agents.research.main import ResearchAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("research")
    agent = ResearchAgent("research", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "customer_sentiment", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("monthly_sentiment_failed", product=product, error=str(exc))


@app.task(name="agents.research.tasks.quarterly_feature_gap_analysis", ignore_result=True)
def quarterly_feature_gap_analysis() -> None:
    """Run quarterly — feature gap analysis per product."""
    import uuid

    from agents._base import AgentConfig
    from agents.research.main import ResearchAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("research")
    agent = ResearchAgent("research", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "feature_gap_analysis", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("quarterly_gap_analysis_failed", product=product, error=str(exc))


@app.task(name="agents.research.tasks.quarterly_pricing_research", ignore_result=True)
def quarterly_pricing_research() -> None:
    """Run quarterly — pricing positioning research per product."""
    import uuid

    from agents._base import AgentConfig
    from agents.research.main import ResearchAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("research")
    agent = ResearchAgent("research", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "pricing_research", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("quarterly_pricing_research_failed", product=product, error=str(exc))
