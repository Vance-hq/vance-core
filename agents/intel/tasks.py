"""Celery tasks for the intel agent."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.intel.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.intel.tasks.daily_intel_scan", ignore_result=True)
def daily_intel_scan() -> None:
    """Run daily — news scan, keyword tracking, and digest per product."""
    import uuid

    from agents._base import AgentConfig
    from agents.intel.main import IntelAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("intel")
    agent = IntelAgent("intel", config)

    for product in config.custom.get("products", {}):
        for action in ("scan_industry_news", "track_keyword", "digest_intel"):
            task = Task(
                id=str(uuid.uuid4()),
                agent=AgentCapability.INTEL,
                payload={"action": action, "product": product},
            )
            try:
                agent.handle(task)
            except Exception as exc:
                logger.error("daily_intel_scan_failed", action=action, product=product, error=str(exc))


@app.task(name="agents.intel.tasks.weekly_competitor_social", ignore_result=True)
def weekly_competitor_social() -> None:
    """Run weekly — competitor social monitoring and market shift detection."""
    import uuid

    from agents._base import AgentConfig
    from agents.intel.main import IntelAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("intel")
    agent = IntelAgent("intel", config)

    for product in config.custom.get("products", {}):
        for action in ("monitor_competitors_social", "detect_market_shift"):
            task = Task(
                id=str(uuid.uuid4()),
                agent=AgentCapability.INTEL,
                payload={"action": action, "product": product},
            )
            try:
                agent.handle(task)
            except Exception as exc:
                logger.error("weekly_competitor_social_failed", action=action, product=product, error=str(exc))


@app.task(name="agents.intel.tasks.competitor_activity_watch", ignore_result=True)
def competitor_activity_watch() -> None:
    """Run every 6 hours — visual diff + blog/LinkedIn/jobs/G2 monitoring per product."""
    import uuid

    from agents._base import AgentConfig
    from agents.intel.main import IntelAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("intel")
    agent = IntelAgent("intel", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.INTEL,
            payload={"action": "competitor_activity_watch", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("competitor_activity_watch_failed", product=product, error=str(exc))


@app.task(name="agents.intel.tasks.daily_press_monitoring", ignore_result=True)
def daily_press_monitoring() -> None:
    """Run daily — SerpAPI news search for product/founder/competitor mentions."""
    import uuid

    from agents._base import AgentConfig
    from agents.intel.main import IntelAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("intel")
    agent = IntelAgent("intel", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.INTEL,
            payload={"action": "press_monitoring", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("daily_press_monitoring_failed", product=product, error=str(exc))


@app.task(name="agents.intel.tasks.daily_community_listen", ignore_result=True)
def daily_community_listen() -> None:
    """Run daily — Reddit + Facebook community monitoring per product."""
    import uuid

    from agents._base import AgentConfig
    from agents.intel.main import IntelAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("intel")
    agent = IntelAgent("intel", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.INTEL,
            payload={"action": "community_listen", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("daily_community_listen_failed", product=product, error=str(exc))


@app.task(name="agents.intel.tasks.monthly_opportunity_scan", ignore_result=True)
def monthly_opportunity_scan() -> None:
    """Run monthly — ProductHunt, API integrations, affiliate partners scored by LLM."""
    import uuid

    from agents._base import AgentConfig
    from agents.intel.main import IntelAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("intel")
    agent = IntelAgent("intel", config)

    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.INTEL,
        payload={"action": "opportunity_scan"},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("monthly_opportunity_scan_failed", error=str(exc))
