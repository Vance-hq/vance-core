"""Celery tasks for the ads agent."""

from __future__ import annotations

from shared.celery_app import app


@app.task(name="agents.ads.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.ads.tasks.daily_monitor_performance", ignore_result=True)
def daily_monitor_performance() -> None:
    """Pull metrics, run LLM analysis, auto-pause / auto-scale — daily."""
    from agents._base import AgentConfig
    from agents.ads.campaign_manager import CampaignManager
    from agents.ads.db import AdsDB
    from agents.ads.performance_monitor import PerformanceMonitor
    from shared.logger import get_logger

    cfg = AgentConfig.load("ads").custom
    db = AdsDB()
    mgr = CampaignManager(db, cfg)
    result = PerformanceMonitor(db, mgr, cfg).run()
    get_logger(__name__).info("daily_monitor_performance_ran", **result)


@app.task(name="agents.ads.tasks.daily_rotate_creative", ignore_result=True)
def daily_rotate_creative() -> None:
    """Check for creative fatigue and resolve A/B tests — daily."""
    from agents._base import AgentConfig
    from agents.ads.creative_gen import CreativeGenerator
    from agents.ads.creative_rotator import CreativeRotator
    from agents.ads.db import AdsDB
    from shared.logger import get_logger

    cfg = AgentConfig.load("ads").custom
    db = AdsDB()
    result = CreativeRotator(db, CreativeGenerator(), cfg).run()
    get_logger(__name__).info("daily_rotate_creative_ran", **result)


@app.task(name="agents.ads.tasks.weekly_budget_realloc", ignore_result=True)
def weekly_budget_realloc() -> None:
    """Rebalance budget across campaigns by ROAS — weekly."""
    from agents._base import AgentConfig
    from agents.ads.budget_reallocator import BudgetReallocator
    from agents.ads.campaign_manager import CampaignManager
    from agents.ads.db import AdsDB
    from shared.logger import get_logger

    cfg = AgentConfig.load("ads").custom
    db = AdsDB()
    mgr = CampaignManager(db, cfg)
    result = BudgetReallocator(db, mgr, cfg).rebalance()
    get_logger(__name__).info("weekly_budget_realloc_ran", **result)


@app.task(name="agents.ads.tasks.monthly_audience_expand", ignore_result=True)
def monthly_audience_expand() -> None:
    """Expand audiences via lookalike creation — monthly."""
    from agents._base import AgentConfig
    from agents.ads.audience_builder import AudienceBuilder
    from agents.ads.db import AdsDB
    from shared.logger import get_logger

    cfg = AgentConfig.load("ads").custom
    db = AdsDB()
    result = AudienceBuilder(db, cfg).expand_all_due()
    get_logger(__name__).info("monthly_audience_expand_ran", **result)
