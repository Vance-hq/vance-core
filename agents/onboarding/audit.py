"""
OnboardingAudit — weekly funnel metrics review.

LLM identifies biggest drop-off step and proposes a fix.
Enqueues to content agent (copy changes) or dev agent (flow changes).
"""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import OnboardingDB

logger = get_logger(__name__)

_AUDIT_SYSTEM = (
    "You are a growth analyst reviewing onboarding funnel metrics. "
    "Identify the single biggest drop-off step and propose one specific change. "
    "Reply with JSON only: {\"biggest_dropoff_step\": str, \"proposal\": str, \"action_type\": \"content\" | \"dev\"}."
)


def enqueue_content_task(product: str, proposal: str, dropoff_step: str) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="content",
            payload={
                "action": "write_copy",
                "product": product,
                "context": f"Onboarding dropoff at {dropoff_step}. Proposal: {proposal}",
            },
        )
    except Exception as exc:
        logger.warning("enqueue_content_failed", product=product, error=str(exc))


def enqueue_dev_task(product: str, proposal: str, dropoff_step: str) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="dev",
            payload={
                "action": "fix_bug",
                "product": product,
                "description": f"Onboarding flow fix at {dropoff_step}: {proposal}",
                "priority": "P2",
            },
        )
    except Exception as exc:
        logger.warning("enqueue_dev_failed", product=product, error=str(exc))


class OnboardingAudit:

    def __init__(self, db: OnboardingDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        metrics = self._db.get_funnel_metrics(product=product)

        prompt = (
            f"Product: {product}\n"
            f"Signup-to-activated %: {metrics.get('signup_to_activated_pct', 0):.1f}%\n"
            f"Avg days to first value: {metrics.get('avg_days_to_first_value', 0):.1f}\n\n"
            "Identify the biggest drop-off and propose one fix."
        )

        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_AUDIT_SYSTEM,
            max_tokens=256,
        )
        raw = resp.content[0].text.strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {
                "biggest_dropoff_step": "unknown",
                "proposal": raw,
                "action_type": "content",
            }

        biggest_dropoff = parsed.get("biggest_dropoff_step", "unknown")
        proposal = parsed.get("proposal", "")
        action_type = parsed.get("action_type", "content")

        if action_type == "content":
            enqueue_content_task(product=product, proposal=proposal, dropoff_step=biggest_dropoff)
        else:
            enqueue_dev_task(product=product, proposal=proposal, dropoff_step=biggest_dropoff)

        logger.info("onboarding_audit_complete", product=product, dropoff=biggest_dropoff, action_type=action_type)
        return {
            "product": product,
            "signup_to_activated_pct": metrics.get("signup_to_activated_pct", 0),
            "avg_days_to_first_value": metrics.get("avg_days_to_first_value", 0),
            "biggest_dropoff_step": biggest_dropoff,
            "proposal": proposal,
            "action_type": action_type,
        }
