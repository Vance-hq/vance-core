"""
Celery application — central task queue and beat scheduler.
All agent background tasks and cron jobs are registered here.
No agent module should create its own Celery app.
"""
from __future__ import annotations

from celery import Celery

from shared.config.settings import settings

app = Celery(
    "vance",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "agents.marketing.tasks",
        "agents.outreach.tasks",
        "agents.sales.tasks",
        "agents.reviews.tasks",
        "agents.ads.tasks",
        "agents.content.tasks",
        "agents.video.tasks",
        "agents.viral.tasks",
        "agents.seo.tasks",
        "agents.support.tasks",
        "agents.dev.tasks",
        "agents.qa.tasks",
        "agents.onboarding.tasks",
        "agents.research.tasks",
        "agents.launch.tasks",
        "agents.security.tasks",
        "agents.deploy.tasks",
        "agents.finance.tasks",
        "agents.backup.tasks",
        "agents.scaling.tasks",
        "agents.analytics.tasks",
        "agents.intel.tasks",
        "agents.memory.tasks",
        "agents.reporting.tasks",
        "agents.strategy.tasks",
        "agents.forge.tasks",
        "agents.localrankgrader.tasks",
        "agents.integrations.tasks",
    ],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "agents.marketing.*": {"queue": "marketing"},
        "agents.outreach.*": {"queue": "outreach"},
        "agents.sales.*": {"queue": "sales"},
        "agents.reviews.*": {"queue": "reviews"},
        "agents.ads.*": {"queue": "ads"},
        "agents.content.*": {"queue": "content"},
        "agents.video.*": {"queue": "video"},
        "agents.viral.*": {"queue": "viral"},
        "agents.seo.*": {"queue": "seo"},
        "agents.support.*": {"queue": "support"},
        "agents.dev.*": {"queue": "dev"},
        "agents.qa.*": {"queue": "qa"},
        "agents.onboarding.*": {"queue": "onboarding"},
        "agents.research.*": {"queue": "research"},
        "agents.launch.*": {"queue": "launch"},
        "agents.security.*": {"queue": "security"},
        "agents.deploy.*": {"queue": "deploy"},
        "agents.finance.*": {"queue": "finance"},
        "agents.backup.*": {"queue": "backup"},
        "agents.scaling.*": {"queue": "scaling"},
        "agents.analytics.*": {"queue": "analytics"},
        "agents.intel.*": {"queue": "intel"},
        "agents.memory.*": {"queue": "memory"},
        "agents.reporting.*": {"queue": "reporting"},
        "agents.strategy.*": {"queue": "strategy"},
        "agents.forge.*": {"queue": "forge"},
        "agents.localrankgrader.*": {"queue": "localrankgrader"},
        "agents.integrations.*": {"queue": "integrations"},
    },
)

# Cron schedule — all recurring tasks defined here, not in individual agents.
app.conf.beat_schedule = {
    "daily-brief": {
        "task": "agents.marketing.tasks.daily_brief",
        "schedule": 86_400.0,
    },
    "trend-monitor": {
        "task": "agents.marketing.tasks.trend_monitor",
        "schedule": 3_600.0,
    },
    "outreach-dispatch-due-sequences": {
        "task": "agents.outreach.tasks.dispatch_due_sequences",
        "schedule": 300.0,  # every 5 minutes
    },
    "analytics-revenue-snapshot": {
        "task": "agents.analytics.tasks.revenue_snapshot",
        "schedule": 3_600.0,
    },
    "security-uptime-check": {
        "task": "agents.security.tasks.uptime_check",
        "schedule": 60.0,
    },
    "forge-lead-score": {
        "task": "agents.forge.tasks.score_all_leads",
        "schedule": 1_800.0,  # every 30m
    },
    "forge-report": {
        "task": "agents.forge.tasks.daily_report",
        "schedule": 86_400.0,
    },
    "grader-daily-analytics": {
        "task": "agents.localrankgrader.tasks.grader_daily_analytics",
        "schedule": 86_400.0,
    },
    "grader-monthly-seo-publish": {
        "task": "agents.localrankgrader.tasks.grader_monthly_seo_publish",
        # Roughly once per month (30 days)
        "schedule": 30 * 86_400.0,
    },
    "analytics-weekly-growth-report": {
        "task": "agents.analytics.tasks.weekly_growth_report",
        "schedule": 7 * 86_400.0,
    },
    "sales-daily-trial-nudge": {
        "task": "agents.sales.tasks.daily_trial_nudge",
        "schedule": 86_400.0,
    },
    "sales-daily-upgrade-nudge": {
        "task": "agents.sales.tasks.daily_upgrade_nudge",
        "schedule": 86_400.0,
    },
    "sales-weekly-win-back": {
        "task": "agents.sales.tasks.weekly_win_back",
        "schedule": 7 * 86_400.0,
    },
    "sales-weekly-referral-trigger": {
        "task": "agents.sales.tasks.weekly_referral_trigger",
        "schedule": 7 * 86_400.0,
    },
    "sales-weekly-pricing-intel": {
        "task": "agents.sales.tasks.weekly_pricing_intel",
        "schedule": 7 * 86_400.0,
    },
    "reviews-poll-gbp": {
        "task": "agents.reviews.tasks.poll_reviews_gbp",
        "schedule": 4 * 3_600.0,  # every 4 hours
    },
    "reviews-poll-yelp-facebook": {
        "task": "agents.reviews.tasks.poll_reviews_yelp_facebook",
        "schedule": 6 * 3_600.0,  # every 6 hours
    },
    "reviews-check-reputation": {
        "task": "agents.reviews.tasks.check_reputation_scores",
        "schedule": 86_400.0,  # daily
    },
}
