"""Celery tasks for the onboarding agent — stuck-user scan + weekly audit."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.onboarding.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.onboarding.tasks.daily_stuck_user_scan", ignore_result=True)
def daily_stuck_user_scan() -> None:
    """Run daily — alert users who signed up 5+ days ago without any activity."""
    import uuid

    from agents._base import AgentConfig
    from agents.onboarding.main import OnboardingAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("onboarding")
    agent = OnboardingAgent("onboarding", config)

    # user_lookup must be populated from Supabase/auth in production;
    # the task pushes an empty dict so the agent can fetch emails internally.
    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.MARKETING,
        payload={"action": "stuck_user_alert", "user_lookup": {}},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("daily_stuck_user_scan_failed", error=str(exc))


@app.task(name="agents.onboarding.tasks.weekly_onboarding_audit", ignore_result=True)
def weekly_onboarding_audit() -> None:
    """Run weekly — funnel metrics review per product."""
    import uuid

    from agents._base import AgentConfig
    from agents.onboarding.main import OnboardingAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("onboarding")
    agent = OnboardingAgent("onboarding", config)

    products = list(config.custom.get("products", {}).keys())
    for product in products:
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "onboarding_audit", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("weekly_onboarding_audit_failed", product=product, error=str(exc))
