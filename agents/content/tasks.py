"""Celery tasks for the content agent."""

from __future__ import annotations

from typing import Any

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.content.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.content.tasks.schedule_content_entry", ignore_result=True)
def schedule_content_entry(entry_id: str, entry: dict[str, Any]) -> None:
    """Fire a content task from a calendar entry on its scheduled date."""
    from agents._base import AgentConfig
    from agents.content.main import ContentAgent

    config = AgentConfig.load("content")
    agent = ContentAgent("content", config)

    platform = entry.get("platform", "")
    content_type = entry.get("type", "")
    product = entry.get("product", "")
    topic = entry.get("topic", "")

    if content_type == "blog_post":
        action = "write_blog_post"
        payload: dict[str, Any] = {
            "action": action,
            "product": product,
            "topic": topic,
            "target_audience": "",
            "word_count": 800,
        }
    elif content_type == "newsletter":
        action = "write_newsletter"
        payload = {"action": action, "product": product}
    else:
        action = "write_social_post"
        payload = {
            "action": action,
            "product": product,
            "platform": platform,
            "topic": topic,
        }

    from shared.types import AgentCapability, Task
    import uuid

    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.MARKETING,
        payload=payload,
    )

    try:
        result = agent.handle(task)
        if result.success:
            from agents.content.db import ContentDB
            ContentDB().update_calendar_entry(entry_id, status="done", content_id=result.output.get("piece_id"))
            logger.info("content_calendar_entry_done", entry_id=entry_id)
        else:
            logger.warning("content_calendar_entry_failed", entry_id=entry_id, output=result.output)
    except Exception as exc:
        logger.error("content_calendar_entry_error", entry_id=entry_id, error=str(exc))


@app.task(name="agents.content.tasks.weekly_newsletters", ignore_result=True)
def weekly_newsletters() -> None:
    """Send weekly newsletters for all active products."""
    from agents._base import AgentConfig
    from agents.content.main import ContentAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("content")
    agent = ContentAgent("content", config)

    products = list((config.custom.get("products") or {}).keys())
    for product in products:
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "write_newsletter", "product": product, "send": True},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("weekly_newsletter_failed", product=product, error=str(exc))


@app.task(name="agents.content.tasks.monthly_calendar", ignore_result=True)
def monthly_calendar() -> None:
    """Plan next 30 days of content for all active products."""
    from agents._base import AgentConfig
    from agents.content.main import ContentAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("content")
    agent = ContentAgent("content", config)

    products = list((config.custom.get("products") or {}).keys())
    for product in products:
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "content_calendar", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("monthly_calendar_failed", product=product, error=str(exc))
