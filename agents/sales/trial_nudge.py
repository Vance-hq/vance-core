"""
Trial nudge — detect stalled trials and re-engage with a product-specific hook.

Runs daily via Celery beat. Skips users already nudged within 7 days.
"""

from __future__ import annotations

from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import SalesDB
from .mailer import SalesMailer, DUTCH_VOICE

logger = get_logger(__name__)

# Product-specific hooks — premise of the nudge email, not a template.
# LLM uses this as the angle to generate the full message.
_PRODUCT_HOOKS: dict[str, str] = {
    "starpio": (
        "You set up your account but haven't responded to your first review yet. "
        "Explain why the first response sets the tone for all future reviews, "
        "and what a missed response communicates to potential guests."
    ),
    "oneserv": (
        "Their first job dispatch is 3 clicks away. Walk them through exactly "
        "which 3 clicks those are and what happens after the first job is dispatched. "
        "Make it feel trivially easy."
    ),
    "localoutrank": (
        "Their Google Business Profile score report is ready. Lead with one specific "
        "finding from a typical report — something concrete a local business almost "
        "always gets wrong — and say the full report is waiting in their account."
    ),
}

_NUDGE_SUBJECT_SYSTEM = "Write a concise email subject line only — no quotes, max 8 words. No clickbait."

_NUDGE_COOLDOWN_DAYS = 7


class TrialNudge:

    def __init__(self, db: SalesDB, mailer: SalesMailer, cfg: dict[str, Any]) -> None:
        self._db = db
        self._mailer = mailer
        self._stall_days = int(cfg.get("trial_nudge_stall_days", 3))
        self._inactivity_hours = int(cfg.get("trial_nudge_inactivity_hours", 48))
        self._from_email = cfg.get("from_email", "")
        self._from_name = cfg.get("from_name", "Dutch")
        self._from_password = cfg.get("from_password", "")

    def run(self) -> dict[str, Any]:
        users = self._db.stalled_trials(self._stall_days, self._inactivity_hours)
        sent = 0
        skipped = 0

        for user in users:
            user_id = str(user["id"])
            product = user["product"]

            days_since = self._db.days_since_last_action(user_id, "trial_nudge")
            if days_since < _NUDGE_COOLDOWN_DAYS:
                skipped += 1
                continue

            hook = _PRODUCT_HOOKS.get(product)
            if not hook:
                skipped += 1
                continue

            try:
                subject, body = self._generate_email(user, product, hook)
                self._mailer.send(
                    to_email=user["email"],
                    to_name=user.get("company") or "",
                    subject=subject,
                    body_text=body,
                    from_email=self._from_email,
                    from_name=self._from_name,
                    from_password=self._from_password,
                )
                self._db.log_action(
                    product=product,
                    action_type="trial_nudge",
                    user_id=user_id,
                    meta={"subject": subject, "hook": product},
                )
                sent += 1
                logger.info("trial_nudge_sent", user_id=user_id, product=product)
            except Exception as exc:
                logger.error("trial_nudge_failed", user_id=user_id, error=str(exc))

        return {"sent": sent, "skipped": skipped, "total_stalled": len(users)}

    def _generate_email(self, user: dict[str, Any], product: str, hook: str) -> tuple[str, str]:
        name = user.get("company") or user.get("email", "").split("@")[0]
        prompt = (
            f"Recipient: {name} (signed up for {product} {self._stall_days}+ days ago, hasn't been active)\n\n"
            f"Email premise: {hook}\n\n"
            "Write the email body."
        )
        body = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=DUTCH_VOICE,
            max_tokens=200,
            metadata={"caller": "sales.trial_nudge"},
        ).content[0].text.strip()

        subject = llm.complete(
            messages=[{"role": "user", "content": f"Email body:\n{body}"}],
            system=_NUDGE_SUBJECT_SYSTEM,
            max_tokens=20,
            metadata={"caller": "sales.trial_nudge.subject"},
        ).content[0].text.strip()

        return subject, body
