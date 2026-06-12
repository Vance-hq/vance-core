"""Celery tasks for the SEO agent — weekly rank tracking, monthly citation audits."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.seo.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.seo.tasks.weekly_rank_track", ignore_result=True)
def weekly_rank_track() -> None:
    """Run weekly — track keyword rankings for all products."""
    from agents._base import AgentConfig
    from agents.seo.main import SeoAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("seo")
    agent = SeoAgent("seo", config)

    product_keywords: dict[str, list[str]] = config.custom.get("tracked_keywords", {})
    for product, keywords in product_keywords.items():
        if not keywords:
            continue
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "rank_tracker", "product": product, "keywords": keywords},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("weekly_rank_track_failed", product=product, error=str(exc))


@app.task(name="agents.seo.tasks.monthly_citation_audit", ignore_result=True)
def monthly_citation_audit() -> None:
    """Run monthly — audit NAP consistency for all businesses."""
    from agents._base import AgentConfig
    from agents.seo.main import SeoAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("seo")
    agent = SeoAgent("seo", config)

    businesses = list(config.custom.get("businesses", {}).keys())
    for business in businesses:
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "citation_audit", "business": business},
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("monthly_citation_audit_failed", business=business, error=str(exc))


@app.task(name="agents.seo.tasks.gbp_optimize_all", ignore_result=True)
def gbp_optimize_all() -> None:
    """Run weekly — optimize all configured GBP profiles."""
    from agents._base import AgentConfig
    from agents.seo.main import SeoAgent
    from shared.types import AgentCapability, Task
    import uuid

    config = AgentConfig.load("seo")
    agent = SeoAgent("seo", config)

    businesses = config.custom.get("businesses", {})
    for business, biz_cfg in businesses.items():
        location_id = biz_cfg.get("gbp_location_id", "")
        if not location_id:
            continue
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "gbp_optimize",
                "business": business,
                "gbp_location_id": location_id,
            },
        )
        try:
            agent.handle(task)
        except Exception as exc:
            logger.error("gbp_optimize_failed", business=business, error=str(exc))
