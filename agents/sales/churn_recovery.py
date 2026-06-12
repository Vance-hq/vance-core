"""
Churn recovery — triggered by Stripe cancel webhook or manual call.

Immediate action:
  1. Pull usage history from Postgres
  2. LLM generates a personal email (Dutch's voice) — not a template
  3. Apply a 30-day free extension via Stripe trial_end update
  4. Log churn_recovery_attempts

The offer is explicit: 30-day extension, no pitch, just "tell me what broke."
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from agents.integrations.connectors.stripe import StripeConnector
from shared.llm.client import llm
from shared.logger import get_logger

from .db import SalesDB
from .mailer import SalesMailer, DUTCH_VOICE

logger = get_logger(__name__)

_RECOVERY_SYSTEM = DUTCH_VOICE + """

You are writing a churn recovery email. Additional rules:
- This is NOT a save-the-deal pitch. It is a genuine human ask.
- Lead with something specific about how they actually used the product.
- The only offer: a 30-day free extension so they can take another look.
- The only ask: tell me what broke. One sentence. That's it.
- Do NOT mention competitors. Do NOT list features. Do NOT use bullet points.
- Max 5 sentences total. Output body only, no subject line.
"""

_SUBJECT_SYSTEM = "Write a concise email subject line only — no quotes, max 8 words. Plain, not clickbait."

_EXTENSION_DAYS = 30


class ChurnRecovery:

    def __init__(self, db: SalesDB, mailer: SalesMailer, cfg: dict[str, Any]) -> None:
        self._db = db
        self._mailer = mailer
        self._from_email = cfg.get("from_email", "")
        self._from_name = cfg.get("from_name", "Dutch")
        self._from_password = cfg.get("from_password", "")
        self._extension_days = int(cfg.get("trial_extension_days", _EXTENSION_DAYS))

    def recover(self, user_id: str) -> dict[str, Any]:
        user = self._db.get_user(user_id)
        if not user:
            return {"error": "user_not_found"}

        usage = self._db.user_usage_summary(user_id)
        subject, body = self._generate_email(user, usage)

        # Apply Stripe extension before sending so the offer is live
        coupon_id = None
        extension_applied = False
        if user.get("stripe_sub_id"):
            try:
                coupon_id = self._apply_extension(user["stripe_sub_id"])
                extension_applied = True
            except Exception as exc:
                logger.warning("stripe_extension_failed", user_id=user_id, error=str(exc))

        try:
            self._mailer.send(
                to_email=user["email"],
                to_name=user.get("company") or "",
                subject=subject,
                body_text=body,
                from_email=self._from_email,
                from_name=self._from_name,
                from_password=self._from_password,
            )
        except Exception as exc:
            logger.error("churn_recovery_send_failed", user_id=user_id, error=str(exc))
            return {"error": str(exc)}

        attempt_id = self._db.log_churn_recovery(
            user_id=user_id,
            product=user["product"],
            extension_applied=extension_applied,
            stripe_coupon_id=coupon_id,
        )
        self._db.log_action(
            product=user["product"],
            action_type="churn_recovery",
            user_id=user_id,
            meta={"subject": subject, "attempt_id": attempt_id, "extension_applied": extension_applied},
        )

        logger.info(
            "churn_recovery_sent",
            user_id=user_id,
            product=user["product"],
            extension_applied=extension_applied,
        )
        return {
            "sent": True,
            "attempt_id": attempt_id,
            "extension_applied": extension_applied,
            "stripe_coupon_id": coupon_id,
        }

    # ------------------------------------------------------------------

    def _generate_email(self, user: dict[str, Any], usage: dict[str, Any]) -> tuple[str, str]:
        name = user.get("company") or user.get("email", "").split("@")[0]
        days_active = usage.get("days_active", 0)
        features_used = usage.get("features_used", 0)
        blocked = usage.get("blocked_attempts", 0)

        prompt = (
            f"Recipient: {name}, was on {user.get('plan')} plan for {user['product']}\n"
            f"Days active before cancelling: {days_active}\n"
            f"Distinct features used: {features_used}\n"
            f"Times hit plan limits: {blocked}\n"
            f"Extension offer: {self._extension_days} days free, no credit card required\n\n"
            "Write the churn recovery email body. Reference something specific about how "
            "they actually used the product. Make the ask: tell me what broke."
        )
        body = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_RECOVERY_SYSTEM,
            max_tokens=250,
            metadata={"caller": "sales.churn_recovery"},
        ).content[0].text.strip()

        subject = llm.complete(
            messages=[{"role": "user", "content": f"Email body:\n{body}"}],
            system=_SUBJECT_SYSTEM,
            max_tokens=20,
            metadata={"caller": "sales.churn_recovery.subject"},
        ).content[0].text.strip()

        return subject, body

    def _apply_extension(self, stripe_sub_id: str) -> str:
        """Extend trial_end by N days. Returns a descriptive coupon ID string."""
        stripe = StripeConnector(called_by="sales", method_name="extend_trial")
        new_trial_end = int(
            (datetime.now(timezone.utc) + timedelta(days=self._extension_days)).timestamp()
        )
        stripe.update_subscription(stripe_sub_id, trial_end=new_trial_end)
        return f"trial_ext_{self._extension_days}d"
