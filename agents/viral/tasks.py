"""Celery tasks for the viral agent — scheduled runs and on-demand piece creation."""

from __future__ import annotations

from typing import Any

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.viral.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.viral.tasks.scan_trends", ignore_result=True)
def scan_trends() -> None:
    """Run every 3 hours via Celery beat — scan all products for trending topics."""
    from agents._base import AgentConfig
    from agents.viral.main import ViralAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("viral")
    agent = ViralAgent("viral", config)
    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.MARKETING,
        payload={"action": "trend_monitor"},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("scan_trends_failed", error=str(exc))


@app.task(name="agents.viral.tasks.create_viral_piece_task", ignore_result=True)
def create_viral_piece_task(
    trend_id: str,
    trend_topic: str,
    product: str,
    platform: str,
    opportunity_window_hours: int,
) -> None:
    """Enqueued immediately when a qualifying trend is detected."""
    from agents._base import AgentConfig
    from agents.viral.main import ViralAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("viral")
    agent = ViralAgent("viral", config)
    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.MARKETING,
        payload={
            "action": "create_viral_piece",
            "trend_id": trend_id,
            "trend_topic": trend_topic,
            "product": product,
            "platform": platform,
            "opportunity_window_hours": opportunity_window_hours,
        },
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("create_viral_piece_task_failed", trend_id=trend_id, error=str(exc))


@app.task(name="agents.viral.tasks.weekly_remix", ignore_result=True)
def weekly_remix() -> None:
    """Run weekly — remix top-performing pieces across platforms."""
    from agents._base import AgentConfig
    from agents.viral.main import ViralAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("viral")
    agent = ViralAgent("viral", config)
    products = list((config.custom.get("products") or []))

    for product in products:
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "remix_winner", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("weekly_remix_failed", product=product, error=str(exc))


@app.task(name="agents.viral.tasks.monthly_gap_analysis", ignore_result=True)
def monthly_gap_analysis() -> None:
    """Run monthly — find competitor content gaps and enqueue blog posts."""
    from agents._base import AgentConfig
    from agents.viral.main import ViralAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("viral")
    agent = ViralAgent("viral", config)
    products = list((config.custom.get("products") or []))

    for product in products:
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "competitor_content_gap", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("monthly_gap_analysis_failed", product=product, error=str(exc))
