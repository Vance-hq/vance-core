"""Celery scheduled tasks for the finance agent."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


def _agent():
    from agents._base import AgentConfig
    from agents.finance.main import FinanceAgent

    config = AgentConfig.load("finance")
    return FinanceAgent("finance", config)


def _task(action: str, **payload):
    import uuid
    from shared.types import AgentCapability, Task

    return Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.FINANCE,
        payload={"action": action, **payload},
    )


@app.task(name="agents.finance.tasks.daily_mrr_snapshot", ignore_result=True)
def daily_mrr_snapshot() -> None:
    """Run daily — snapshot MRR per product from Stripe."""
    try:
        _agent().handle(_task("mrr_snapshot"))
    except Exception as exc:
        logger.error("daily_mrr_snapshot_failed", error=str(exc))


@app.task(name="agents.finance.tasks.monthly_cost_tracking", ignore_result=True)
def monthly_cost_tracking() -> None:
    """Run monthly — collect infra/tool costs and compute gross margin."""
    try:
        _agent().handle(_task("cost_tracking"))
    except Exception as exc:
        logger.error("monthly_cost_tracking_failed", error=str(exc))


@app.task(name="agents.finance.tasks.monthly_revenue_forecast", ignore_result=True)
def monthly_revenue_forecast() -> None:
    """Run monthly — generate 90-day revenue forecast."""
    try:
        _agent().handle(_task("revenue_forecast"))
    except Exception as exc:
        logger.error("monthly_revenue_forecast_failed", error=str(exc))


@app.task(name="agents.finance.tasks.monthly_unit_economics", ignore_result=True)
def monthly_unit_economics(
    sales_marketing_spend_cents: int = 0,
    new_customers: int = 0,
) -> None:
    """Run monthly — calculate CAC, LTV, payback period."""
    try:
        _agent().handle(_task(
            "unit_economics",
            sales_marketing_spend_cents=sales_marketing_spend_cents,
            new_customers=new_customers,
        ))
    except Exception as exc:
        logger.error("monthly_unit_economics_failed", error=str(exc))


@app.task(name="agents.finance.tasks.stripe_webhook_anomaly", ignore_result=True)
def stripe_webhook_anomaly(event: dict) -> None:
    """Triggered by Stripe webhook handler on charge/refund/cancel/failed-payment events."""
    try:
        _agent().handle(_task("anomaly_detect", event=event))
    except Exception as exc:
        logger.error("stripe_webhook_anomaly_failed", error=str(exc))
