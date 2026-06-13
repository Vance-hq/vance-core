"""Celery tasks for the analytics agent — daily/weekly/monthly schedules."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.analytics.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.analytics.tasks.daily_usage_snapshot", ignore_result=True)
def daily_usage_snapshot() -> None:
    """Run daily — capture usage metrics for all products."""
    import uuid

    from agents._base import AgentConfig
    from agents.analytics.main import AnalyticsAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("analytics")
    agent = AnalyticsAgent("analytics", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.ANALYTICS,
            payload={"action": "usage_snapshot", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("daily_usage_snapshot_failed", product=product, error=str(exc))


@app.task(name="agents.analytics.tasks.daily_cross_product_report", ignore_result=True)
def daily_cross_product_report() -> None:
    """Run daily — unified cross-product view → reporting agent."""
    import uuid

    from agents._base import AgentConfig
    from agents.analytics.main import AnalyticsAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("analytics")
    agent = AnalyticsAgent("analytics", config)
    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.ANALYTICS,
        payload={"action": "cross_product_report"},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("daily_cross_product_report_failed", error=str(exc))


@app.task(name="agents.analytics.tasks.daily_engagement_scores", ignore_result=True)
def daily_engagement_scores() -> None:
    """Run daily — recalculate engagement scores for all products."""
    import uuid

    from agents._base import AgentConfig
    from agents.analytics.main import AnalyticsAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("analytics")
    agent = AnalyticsAgent("analytics", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.ANALYTICS,
            payload={"action": "engagement_score", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("daily_engagement_score_failed", product=product, error=str(exc))


@app.task(name="agents.analytics.tasks.weekly_funnel_analysis", ignore_result=True)
def weekly_funnel_analysis() -> None:
    """Run weekly — funnel + WoW regression check per product."""
    import uuid

    from agents._base import AgentConfig
    from agents.analytics.main import AnalyticsAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("analytics")
    agent = AnalyticsAgent("analytics", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.ANALYTICS,
            payload={"action": "funnel_analysis", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("weekly_funnel_analysis_failed", product=product, error=str(exc))


@app.task(name="agents.analytics.tasks.weekly_feature_usage", ignore_result=True)
def weekly_feature_usage() -> None:
    """Run weekly — feature adoption report per product."""
    import uuid

    from agents._base import AgentConfig
    from agents.analytics.main import AnalyticsAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("analytics")
    agent = AnalyticsAgent("analytics", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.ANALYTICS,
            payload={"action": "feature_usage", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("weekly_feature_usage_failed", product=product, error=str(exc))


@app.task(name="agents.analytics.tasks.weekly_ab_test_check", ignore_result=True)
def weekly_ab_test_check() -> None:
    """Run weekly — check all running A/B tests for significance."""
    import uuid

    from agents._base import AgentConfig
    from agents.analytics.main import AnalyticsAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("analytics")
    agent = AnalyticsAgent("analytics", config)
    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.ANALYTICS,
        payload={"action": "ab_test_tracker", "sub_action": "check_all"},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("weekly_ab_test_check_failed", error=str(exc))


@app.task(name="agents.analytics.tasks.monthly_cohort_analysis", ignore_result=True)
def monthly_cohort_analysis() -> None:
    """Run monthly — cohort retention at 30/60/90 days per product."""
    import uuid

    from agents._base import AgentConfig
    from agents.analytics.main import AnalyticsAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("analytics")
    agent = AnalyticsAgent("analytics", config)

    for product in config.custom.get("products", {}):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.ANALYTICS,
            payload={"action": "cohort_analysis", "product": product},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("monthly_cohort_analysis_failed", product=product, error=str(exc))
