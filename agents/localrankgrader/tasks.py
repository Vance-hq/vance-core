"""Celery tasks for LocalRankGrader async and scheduled operations."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(bind=True, max_retries=3, default_retry_delay=300, queue="grader")
def send_nurture_step(self, lead_id: str, step: int) -> dict:  # type: ignore[override]
    """Send a single nurture email step. Retries up to 3x on SMTP failure."""
    try:
        from agents._base.config import AgentConfig
        from agents.localrankgrader.db import GraderDB
        from agents.localrankgrader.email import GraderMailer
        from agents.localrankgrader.nurture import NurtureSequencer

        config = AgentConfig.load("local_rank_grader")
        db = GraderDB()
        mailer = GraderMailer()
        threshold = config.custom.get("upgrade_nudge_threshold", 80)
        sequencer = NurtureSequencer(db, mailer, upgrade_nudge_threshold=threshold)
        return sequencer.send_step(lead_id=lead_id, step=step)
    except Exception as exc:
        logger.error("nurture_step_task_failed", lead_id=lead_id, step=step, error=str(exc))
        raise self.retry(exc=exc)


@app.task(queue="grader")
def grader_daily_analytics() -> dict:
    """Aggregate daily funnel metrics. Triggered by Celery beat."""
    from agents.localrankgrader.analytics import GraderAnalytics
    from agents.localrankgrader.db import GraderDB

    analytics = GraderAnalytics(GraderDB())
    result = analytics.daily_summary()
    logger.info("grader_daily_analytics_done", **{k: v for k, v in result.items() if not isinstance(v, dict)})
    return result


@app.task(queue="grader")
def grader_monthly_seo_publish() -> dict:
    """Generate anonymised SEO landing pages. Triggered monthly by Celery beat."""
    from agents.localrankgrader.db import GraderDB
    from agents.localrankgrader.publisher import SEOPublisher

    result = SEOPublisher(GraderDB()).publish_monthly()
    logger.info("grader_monthly_seo_done", pages=result.get("pages_generated", 0))
    return result
