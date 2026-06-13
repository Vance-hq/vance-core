"""Celery tasks for the intel agent — daily schedules."""

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
