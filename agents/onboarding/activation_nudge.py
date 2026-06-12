"""
ActivationNudge — push stuck users to their next milestone.

Sends if user hasn't hit next milestone within 48 hours.
Nudge is the single next action — not a feature list.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.logger import get_logger

from .db import OnboardingDB
from .mailer import send_email

logger = get_logger(__name__)

_NUDGE_THRESHOLD_HOURS = 48

_NUDGE_HTML = """
<p>Hey,</p>
<p>One quick thing: you haven't {next_action} yet on {product_name}.</p>
<p><strong>Here's your next step: {milestone_label}.</strong></p>
<p>Takes less than 2 minutes. Once you do it, everything else clicks.</p>
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

_MILESTONE_ACTIONS: dict[str, str] = {
    "connected_gbp": "connected your Google Business Profile",
    "first_review_seen": "checked your first review",
    "first_response_sent": "sent your first AI response",
    "created_account": "completed your profile",
    "first_job": "created a job",
    "first_dispatch": "dispatched a job",
    "first_invoice": "sent an invoice",
    "ran_audit": "run an audit",
    "viewed_report": "viewed your report",
    "applied_first_recommendation": "applied a recommendation",
}


def hours_since(ts: str | datetime | None) -> float:
    if ts is None:
        return float("inf")
    if isinstance(ts, str):
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    else:
        dt = ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return delta.total_seconds() / 3600


class ActivationNudge:

    def __init__(self, db: OnboardingDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def check(
        self,
        user_id: str,
        user_email: str,
        product: str,
    ) -> dict[str, Any]:
        state = self._db.get_state(user_id=user_id, product=product)
        if not state:
            return {"nudge_sent": False, "reason": "no_state", "user_id": user_id}

        current_milestone = state.get("current_milestone", "")
        last_nudge_at = state.get("last_nudge_at")

        if hours_since(last_nudge_at) < _NUDGE_THRESHOLD_HOURS:
            return {
                "nudge_sent": False,
                "reason": "recently_nudged",
                "user_id": user_id,
                "milestone": current_milestone,
            }

        prod_cfg = self._cfg.get("products", {}).get(product, {})
        milestone_label = _MILESTONE_LABELS.get(current_milestone, current_milestone)
        next_action_str = _MILESTONE_ACTIONS.get(current_milestone, current_milestone)

        html = _NUDGE_HTML.format(
            next_action=next_action_str,
            product_name=prod_cfg.get("name", product),
            milestone_label=milestone_label,
        )

        sent = send_email(
            api_key=self._cfg.get("resend_api_key", ""),
            to=user_email,
            from_email=prod_cfg.get("from_email", self._cfg.get("dutch_email", "")),
            from_name=prod_cfg.get("from_name", "Dutch"),
            subject=f"Your next step on {prod_cfg.get('name', product)}: {milestone_label}",
            html=html,
        )

        if sent:
            self._db.upsert_state(
                user_id=user_id,
                product=product,
                current_milestone=current_milestone,
                milestones_completed=state.get("milestones_completed") or [],
                last_nudge_at=datetime.now(timezone.utc),
            )

        logger.info("activation_nudge_sent", user_id=user_id, product=product, milestone=current_milestone, sent=sent)
        return {
            "nudge_sent": sent,
            "user_id": user_id,
            "product": product,
            "milestone": current_milestone,
        }
