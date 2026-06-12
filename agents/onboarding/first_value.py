"""
FirstValueMoment — celebrate when user hits first milestone.

Shows the outcome (not the feature). Triggers NPS at 30 days.
"""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger

from .db import OnboardingDB
from .mailer import send_email

logger = get_logger(__name__)

_NPS_TRIGGER_DAYS = 30

_OUTCOME_COPY: dict[str, dict[str, str]] = {
    "starpio": {
        "first_response_sent": (
            "Your first AI response just went live — here's what it looked like",
            "<p>That response is now live on your Google Business Profile. "
            "Your AI handled it — no copy-paste, no manual drafting.</p>"
            "<p>Every new review from here gets the same treatment.</p>"
        ),
        "first_review_seen": (
            "Your reviews are being tracked",
            "<p>Your AI just pulled your first review. You'll never miss one again.</p>"
        ),
        "connected_gbp": (
            "Your Google Business Profile is connected",
            "<p>Your GBP is live. Your AI can now see and respond to every review.</p>"
        ),
    },
    "oneserv": {
        "first_dispatch": (
            "Job dispatched. Here's your first work order.",
            "<p>Your first work order just went out. Your crew got the details instantly.</p>"
            "<p>That's the whole point — no phone tag, no missed jobs.</p>"
        ),
        "first_job": (
            "First job created",
            "<p>Your first job is in the system. Ready to dispatch when you are.</p>"
        ),
        "first_invoice": (
            "First invoice sent",
            "<p>Your first invoice just went out. Cash flow starts here.</p>"
        ),
        "created_account": (
            "You're set up",
            "<p>Your account is ready. Your first job is one click away.</p>"
        ),
    },
    "localoutrank": {
        "applied_first_recommendation": (
            "First recommendation applied",
            "<p>Your first SEO fix is live. That's how the rankings move — one fix at a time.</p>"
        ),
        "viewed_report": (
            "Your audit report is ready",
            "<p>Your full local SEO report is in. The biggest opportunity is at the top.</p>"
        ),
        "ran_audit": (
            "Audit complete",
            "<p>Your local SEO audit just ran. You'll see exactly where you stand.</p>"
        ),
    },
}

_CELEBRATE_HTML = """
<p>Hey,</p>
<p>{outcome_body}</p>
<p>— Dutch</p>
"""


def enqueue_nps_survey(user_id: str, user_email: str, product: str) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="support",
            payload={
                "action": "nps_survey",
                "sub_action": "send",
                "user_id": user_id,
                "user_email": user_email,
                "product": product,
            },
        )
    except Exception as exc:
        logger.warning("enqueue_nps_failed", user_id=user_id, error=str(exc))


class FirstValueMoment:

    def __init__(self, db: OnboardingDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def celebrate(
        self,
        user_id: str,
        user_email: str,
        product: str,
        milestone: str,
        days_since_signup: int,
    ) -> dict[str, Any]:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        product_copy = _OUTCOME_COPY.get(product, {})
        subject, outcome_body = product_copy.get(
            milestone,
            (f"You hit a milestone on {prod_cfg.get('name', product)}", "<p>Great work — keep going.</p>"),
        )

        html = _CELEBRATE_HTML.format(outcome_body=outcome_body)

        sent = send_email(
            api_key=self._cfg.get("resend_api_key", ""),
            to=user_email,
            from_email=prod_cfg.get("from_email", self._cfg.get("dutch_email", "")),
            from_name=prod_cfg.get("from_name", "Dutch"),
            subject=subject,
            html=html,
        )

        self._db.record_milestone(
            user_id=user_id,
            product=product,
            milestone=milestone,
            days_since_signup=days_since_signup,
        )

        milestones: list[str] = prod_cfg.get("milestones", [])
        current_state = self._db.get_state(user_id=user_id, product=product)
        completed: list[str] = list(current_state.get("milestones_completed") or []) if current_state else []
        if milestone not in completed:
            completed.append(milestone)

        milestone_idx = milestones.index(milestone) if milestone in milestones else -1
        next_milestone = milestones[milestone_idx + 1] if 0 <= milestone_idx < len(milestones) - 1 else milestone

        self._db.upsert_state(
            user_id=user_id,
            product=product,
            current_milestone=next_milestone,
            milestones_completed=completed,
        )

        if days_since_signup >= _NPS_TRIGGER_DAYS:
            enqueue_nps_survey(user_id=user_id, user_email=user_email, product=product)

        logger.info("first_value_celebrated", user_id=user_id, product=product, milestone=milestone, sent=sent)
        return {
            "celebrated": sent,
            "user_id": user_id,
            "product": product,
            "milestone": milestone,
            "next_milestone": next_milestone,
        }
