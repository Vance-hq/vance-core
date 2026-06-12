"""Celery tasks for the support agent — weekly KB updates, NPS surveys, proactive monitoring."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.support.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.support.tasks.weekly_kb_update", ignore_result=True)
def weekly_kb_update() -> None:
    """Run weekly — refresh KB articles from resolved tickets for all products."""
    from agents._base import AgentConfig
    from agents.support.main import SupportAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("support")
    agent = SupportAgent("support", config)

    products = list(config.custom.get("products", {}).keys())
    for product in products:
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "kb_update", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("weekly_kb_update_failed", product=product, error=str(exc))


@app.task(name="agents.support.tasks.daily_proactive_check", ignore_result=True)
def daily_proactive_check() -> None:
    """Run daily — check all products for error spikes and send proactive alerts."""
    from agents._base import AgentConfig
    from agents.support.main import SupportAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("support")
    agent = SupportAgent("support", config)

    products = list(config.custom.get("products", {}).keys())
    for product in products:
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "proactive_support", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("proactive_check_failed", product=product, error=str(exc))


@app.task(name="agents.support.tasks.send_nps_survey", ignore_result=True)
def send_nps_survey(user_id: str, user_email: str, product: str) -> None:
    """Triggered 30 days after signup — send NPS survey to a single user."""
    from agents._base import AgentConfig
    from agents.support.main import SupportAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("support")
    agent = SupportAgent("support", config)

    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.MARKETING,
        payload={
            "action": "nps_survey",
            "sub_action": "send",
            "user_id": user_id,
            "user_email": user_email,
            "product": product,
        },
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("nps_send_failed", user_id=user_id, error=str(exc))
