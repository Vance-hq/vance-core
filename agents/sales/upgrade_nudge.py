"""
Upgrade nudge — identify free/starter users hitting plan limits and prompt an upgrade.

Leading signal: the specific feature they tried to use but were blocked from.
7-day cooldown per user enforced via sales_actions.
"""

from __future__ import annotations

from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import SalesDB
from .mailer import SalesMailer, DUTCH_VOICE

logger = get_logger(__name__)

_UPGRADE_PLANS = ["free", "starter"]
_COOLDOWN_DAYS = 7

_SUBJECT_SYSTEM = "Write a concise email subject line only — no quotes, max 8 words. No clickbait."

# Brief one-liners explaining what each feature unlock gives the user.
_FEATURE_DESCRIPTIONS: dict[str, str] = {
    "bulk_dispatch": "send jobs to multiple techs at once",
    "auto_invoice": "invoices that go out the moment a job is marked complete",
    "review_response": "respond to all reviews from one dashboard",
    "rank_tracking": "weekly rank movement for every keyword you care about",
    "multi_location": "manage all locations under one login",
    "api_access": "push jobs from your existing system directly into the platform",
    "custom_reports": "reports that match how you actually run your business",
    "priority_support": "get answers the same day instead of waiting 3 days",
}


class UpgradeNudge:

    def __init__(self, db: SalesDB, mailer: SalesMailer, cfg: dict[str, Any]) -> None:
        self._db = db
        self._mailer = mailer
        self._from_email = cfg.get("from_email", "")
        self._from_name = cfg.get("from_name", "Dutch")
        self._from_password = cfg.get("from_password", "")

    def run(self) -> dict[str, Any]:
        candidates = self._db.upgrade_candidates(_UPGRADE_PLANS)
        sent = 0
        skipped = 0

        for user in candidates:
            user_id = str(user["id"])
            product = user["product"]

            days_since = self._db.days_since_last_action(user_id, "upgrade_nudge")
            if days_since < _COOLDOWN_DAYS:
                skipped += 1
                continue

            feature = user.get("last_blocked_feature", "")
            blocked_count = int(user.get("blocked_attempts", 0))

            try:
                subject, body = self._generate_email(user, product, feature, blocked_count)
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
                    action_type="upgrade_nudge",
                    user_id=user_id,
                    meta={"feature": feature, "blocked_count": blocked_count, "subject": subject},
                )
                sent += 1
                logger.info("upgrade_nudge_sent", user_id=user_id, product=product, feature=feature)
            except Exception as exc:
                logger.error("upgrade_nudge_failed", user_id=user_id, error=str(exc))

        return {"sent": sent, "skipped": skipped, "total_candidates": len(candidates)}

    def _generate_email(
        self,
        user: dict[str, Any],
        product: str,
        feature: str,
        blocked_count: int,
    ) -> tuple[str, str]:
        feature_desc = _FEATURE_DESCRIPTIONS.get(feature, feature.replace("_", " "))
        name = user.get("company") or user.get("email", "").split("@")[0]

        prompt = (
            f"Recipient: {name} on {user.get('plan', 'starter')} plan for {product}\n"
            f"Feature they tried to use: {feature} ({feature_desc})\n"
            f"Times blocked in last 14 days: {blocked_count}\n\n"
            "Lead with the specific feature they tried. Explain what they're missing in "
            "one concrete sentence. Then make the ask: upgrade. Keep it under 4 sentences."
        )
        body = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=DUTCH_VOICE,
            max_tokens=200,
            metadata={"caller": "sales.upgrade_nudge"},
        ).content[0].text.strip()

        subject = llm.complete(
            messages=[{"role": "user", "content": f"Email body:\n{body}"}],
            system=_SUBJECT_SYSTEM,
            max_tokens=20,
            metadata={"caller": "sales.upgrade_nudge.subject"},
        ).content[0].text.strip()

        return subject, body
