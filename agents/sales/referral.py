"""
Referral trigger — identify happy long-term customers and invite them to refer.

Signals required (all must pass):
  - NPS score >= configurable threshold (default 8)
  - Active for > 30 days
  - No prior referral invite sent

One invite per user, ever. Logged in sales_actions with action_type='referral_invite'.
"""

from __future__ import annotations

from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import SalesDB
from .mailer import SalesMailer, DUTCH_VOICE

logger = get_logger(__name__)

_REFERRAL_SYSTEM = DUTCH_VOICE + """

You are writing a referral program invite. Additional rules:
- They love the product (NPS >= 8) — don't over-explain the value. They know it.
- One sentence on what the referral program offers them (credit, cash, whatever).
- One sentence asking if they know anyone who'd benefit.
- That's it. Under 4 sentences. Output body only.
"""

_SUBJECT_SYSTEM = "Write a concise email subject line only — no quotes, max 8 words."

# Product-specific referral incentives
_REFERRAL_INCENTIVES: dict[str, str] = {
    "starpio": "one free month for every restaurant owner you refer who signs up",
    "oneserv": "one free month for every contractor you refer who runs their first job",
    "localoutrank": "one free month for every business you refer who completes their first audit",
}


class ReferralTrigger:

    def __init__(self, db: SalesDB, mailer: SalesMailer, cfg: dict[str, Any]) -> None:
        self._db = db
        self._mailer = mailer
        self._nps_threshold = int(cfg.get("referral_nps_threshold", 8))
        self._active_days = int(cfg.get("referral_active_days", 30))
        self._from_email = cfg.get("from_email", "")
        self._from_name = cfg.get("from_name", "Dutch")
        self._from_password = cfg.get("from_password", "")

    def run(self) -> dict[str, Any]:
        candidates = self._db.referral_candidates(self._nps_threshold, self._active_days)
        sent = 0

        for user in candidates:
            user_id = str(user["id"])
            product = user["product"]
            incentive = _REFERRAL_INCENTIVES.get(product, "one free month per referral")

            try:
                subject, body = self._generate_email(user, product, incentive)
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
                    action_type="referral_invite",
                    user_id=user_id,
                    meta={"nps_score": user.get("nps_score"), "subject": subject},
                )
                sent += 1
                logger.info("referral_invite_sent", user_id=user_id, product=product)
            except Exception as exc:
                logger.error("referral_invite_failed", user_id=user_id, error=str(exc))

        return {"sent": sent, "total_candidates": len(candidates)}

    def _generate_email(
        self,
        user: dict[str, Any],
        product: str,
        incentive: str,
    ) -> tuple[str, str]:
        name = user.get("company") or user.get("email", "").split("@")[0]
        prompt = (
            f"Recipient: {name}, NPS {user.get('nps_score')} on {product}\n"
            f"Referral incentive: {incentive}\n\n"
            "Write the referral invite email body."
        )
        body = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_REFERRAL_SYSTEM,
            max_tokens=150,
            metadata={"caller": "sales.referral"},
        ).content[0].text.strip()

        subject = llm.complete(
            messages=[{"role": "user", "content": f"Email body:\n{body}"}],
            system=_SUBJECT_SYSTEM,
            max_tokens=20,
            metadata={"caller": "sales.referral.subject"},
        ).content[0].text.strip()

        return subject, body
