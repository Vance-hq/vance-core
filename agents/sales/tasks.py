"""Celery tasks for the sales agent."""

from __future__ import annotations

from shared.celery_app import app


@app.task(name="agents.sales.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.sales.tasks.daily_trial_nudge", ignore_result=True)
def daily_trial_nudge() -> None:
    """Re-engage stalled trial users — runs daily."""
    from agents._base import AgentConfig
    from agents.sales.db import SalesDB
    from agents.sales.mailer import SalesMailer
    from agents.sales.trial_nudge import TrialNudge
    from shared.logger import get_logger

    cfg = AgentConfig.load("sales").custom
    result = TrialNudge(SalesDB(), SalesMailer(), cfg).run()
    get_logger(__name__).info("daily_trial_nudge_ran", **result)


@app.task(name="agents.sales.tasks.daily_upgrade_nudge", ignore_result=True)
def daily_upgrade_nudge() -> None:
    """Nudge free/starter users hitting plan limits — runs daily."""
    from agents._base import AgentConfig
    from agents.sales.db import SalesDB
    from agents.sales.mailer import SalesMailer
    from agents.sales.upgrade_nudge import UpgradeNudge
    from shared.logger import get_logger

    cfg = AgentConfig.load("sales").custom
    result = UpgradeNudge(SalesDB(), SalesMailer(), cfg).run()
    get_logger(__name__).info("daily_upgrade_nudge_ran", **result)


@app.task(name="agents.sales.tasks.weekly_win_back", ignore_result=True)
def weekly_win_back() -> None:
    """Send first win-back email to eligible churned users — runs weekly."""
    from agents._base import AgentConfig
    from agents.sales.db import SalesDB
    from agents.sales.mailer import SalesMailer
    from agents.sales.win_back import WinBack
    from shared.logger import get_logger

    cfg = AgentConfig.load("sales").custom
    result = WinBack(SalesDB(), SalesMailer(), cfg).run()
    get_logger(__name__).info("weekly_win_back_ran", **result)


@app.task(name="agents.sales.tasks.weekly_referral_trigger", ignore_result=True)
def weekly_referral_trigger() -> None:
    """Invite happy customers to refer — runs weekly."""
    from agents._base import AgentConfig
    from agents.sales.db import SalesDB
    from agents.sales.mailer import SalesMailer
    from agents.sales.referral import ReferralTrigger
    from shared.logger import get_logger

    cfg = AgentConfig.load("sales").custom
    result = ReferralTrigger(SalesDB(), SalesMailer(), cfg).run()
    get_logger(__name__).info("weekly_referral_trigger_ran", **result)


@app.task(name="agents.sales.tasks.weekly_pricing_intel", ignore_result=True)
def weekly_pricing_intel() -> None:
    """Scrape competitor pricing and alert on significant changes — runs weekly."""
    from agents._base import AgentConfig
    from agents.sales.db import SalesDB
    from agents.sales.pricing_intel import PricingIntel
    from shared.logger import get_logger

    cfg = AgentConfig.load("sales").custom
    result = PricingIntel(SalesDB(), cfg).run()
    get_logger(__name__).info("weekly_pricing_intel_ran", **result)
