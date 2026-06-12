"""
SignupFlow — triggered on Stripe checkout.session.completed or Supabase auth webhook.

Actions:
  1. Send personal welcome email (from Dutch)
  2. Create onboarding state in DB with first milestone
  3. Enqueue day-1, day-3, day-7 check-in tasks
"""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger

from .db import OnboardingDB
from .mailer import send_email

logger = get_logger(__name__)

_WELCOME_HTML = """
<p>Hey,</p>
<p>Dutch here. You just signed up for {product_name} — I wanted to reach out personally.</p>
<p>Your first step is simple: <strong>{first_milestone_label}</strong>. That's it.</p>
<p>No list of features. Just one thing that'll show you exactly what this can do.</p>
<p>Hit reply if you have any questions — I read every message.</p>
<p>— Dutch</p>
"""

_MILESTONE_LABELS: dict[str, str] = {
    "connected_gbp": "Connect your Google Business Profile",
    "first_review_seen": "Check your first AI-fetched review",
    "first_response_sent": "Send your first AI-drafted response",
    "created_account": "Complete your profile setup",
    "first_job": "Create your first job",
    "first_dispatch": "Dispatch a job to a crew member",
    "first_invoice": "Send your first invoice",
    "ran_audit": "Run your first local SEO audit",
    "viewed_report": "Open your audit report",
    "applied_first_recommendation": "Apply your first recommendation",
}


def enqueue_day1_checkin(user_id: str, user_email: str, product: str) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="onboarding",
            payload={
                "action": "activation_nudge",
                "user_id": user_id,
                "user_email": user_email,
                "product": product,
            },
            priority=6,
        )
    except Exception as exc:
        logger.warning("enqueue_day1_failed", user_id=user_id, error=str(exc))


def enqueue_day3_checkin(user_id: str, user_email: str, product: str) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="onboarding",
            payload={
                "action": "activation_nudge",
                "user_id": user_id,
                "user_email": user_email,
                "product": product,
                "day": 3,
            },
            priority=5,
        )
    except Exception as exc:
        logger.warning("enqueue_day3_failed", user_id=user_id, error=str(exc))


def enqueue_day7_checkin(user_id: str, user_email: str, product: str) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="onboarding",
            payload={
                "action": "activation_nudge",
                "user_id": user_id,
                "user_email": user_email,
                "product": product,
                "day": 7,
            },
            priority=4,
        )
    except Exception as exc:
        logger.warning("enqueue_day7_failed", user_id=user_id, error=str(exc))


class SignupFlow:

    def __init__(self, db: OnboardingDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def trigger(
        self,
        user_id: str,
        user_email: str,
        product: str,
    ) -> dict[str, Any]:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        milestones: list[str] = prod_cfg.get("milestones", [])
        first_milestone = milestones[0] if milestones else ""

        self._db.upsert_state(
            user_id=user_id,
            product=product,
            current_milestone=first_milestone,
            milestones_completed=[],
        )

        first_label = _MILESTONE_LABELS.get(first_milestone, first_milestone)
        html = _WELCOME_HTML.format(
            product_name=prod_cfg.get("name", product),
            first_milestone_label=first_label,
        )

        sent = send_email(
            api_key=self._cfg.get("resend_api_key", ""),
            to=user_email,
            from_email=prod_cfg.get("from_email", self._cfg.get("dutch_email", "")),
            from_name=prod_cfg.get("from_name", "Dutch"),
            subject=f"Welcome to {prod_cfg.get('name', product)} — your one first step",
            html=html,
        )

        enqueue_day1_checkin(user_id=user_id, user_email=user_email, product=product)
        enqueue_day3_checkin(user_id=user_id, user_email=user_email, product=product)
        enqueue_day7_checkin(user_id=user_id, user_email=user_email, product=product)

        logger.info("signup_flow_triggered", user_id=user_id, product=product, welcome_sent=sent)
        return {
            "user_id": user_id,
            "product": product,
            "welcome_sent": sent,
            "checkins_scheduled": 3,
            "first_milestone": first_milestone,
        }
