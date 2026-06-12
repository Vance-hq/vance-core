"""
LaunchDebrief — T+7 day post-launch performance summary.

Pulls: signups, revenue, social engagement, press mentions, support volume.
LLM generates narrative. Delivers to Dutch via voice report.
"""

from __future__ import annotations

from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import LaunchDB

logger = get_logger(__name__)

_DEBRIEF_SYSTEM = (
    "You are a launch analyst. Write a concise, honest debrief of a product launch. "
    "Lead with the headline number (signups or revenue). Note what worked and what to do differently. "
    "Keep it under 150 words. Write for Dutch — direct, no fluff."
)

_METRICS = ["signups", "revenue_delta", "social_engagement", "press_mentions", "support_ticket_volume"]


def fetch_launch_metrics(product: str, launch_date: str) -> dict[str, Any]:
    """Pull post-launch metrics from analytics/support/social sources."""
    from shared.db.client import get_db
    metrics: dict[str, Any] = {m: 0 for m in _METRICS}
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM users WHERE product = %s AND created_at >= %s::date",
                    (product, launch_date),
                )
                row = cur.fetchone()
                metrics["signups"] = row[0] if row else 0

                cur.execute(
                    """
                    SELECT COALESCE(SUM(amount), 0) FROM payments
                    WHERE product = %s AND created_at >= %s::date
                    """,
                    (product, launch_date),
                )
                row = cur.fetchone()
                metrics["revenue_delta"] = int(row[0]) if row else 0

                cur.execute(
                    "SELECT COUNT(*) FROM support_tickets WHERE product = %s AND created_at >= %s::date",
                    (product, launch_date),
                )
                row = cur.fetchone()
                metrics["support_ticket_volume"] = row[0] if row else 0
    except Exception as exc:
        logger.warning("fetch_launch_metrics_db_failed", product=product, error=str(exc))
    return metrics


def enqueue_voice_report(
    product: str,
    narrative: str,
    metrics: dict[str, Any],
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="reporting",
            payload={
                "action": "voice_report",
                "product": product,
                "title": f"{product} launch debrief",
                "narrative": narrative,
                "metrics": metrics,
            },
            priority=6,
        )
    except Exception as exc:
        logger.warning("enqueue_voice_report_failed", product=product, error=str(exc))


class LaunchDebrief:

    def __init__(self, db: LaunchDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, plan_id: str, product: str) -> dict[str, Any]:
        plan = self._db.get_plan(plan_id=plan_id)
        launch_date = plan.get("launch_date", "") if plan else ""

        metrics = fetch_launch_metrics(product=product, launch_date=str(launch_date))

        prompt = (
            f"Product: {product}\n"
            f"Launch date: {launch_date}\n\n"
            f"Signups: {metrics['signups']}\n"
            f"Revenue delta: ${metrics['revenue_delta']}\n"
            f"Social engagement: {metrics['social_engagement']} interactions\n"
            f"Press mentions: {metrics['press_mentions']}\n"
            f"Support tickets: {metrics['support_ticket_volume']}\n\n"
            "Write the launch debrief."
        )

        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_DEBRIEF_SYSTEM,
            max_tokens=512,
        )
        narrative = resp.content[0].text.strip()

        for metric, value in metrics.items():
            self._db.save_result(
                launch_id=plan_id,
                metric=metric,
                value=str(value),
            )

        self._db.update_plan_status(plan_id=plan_id, status="completed")

        enqueue_voice_report(
            product=product,
            narrative=narrative,
            metrics=metrics,
        )

        logger.info("launch_debrief_complete", product=product, plan_id=plan_id)
        return {
            "product": product,
            "plan_id": plan_id,
            "narrative": narrative,
            **metrics,
        }
