"""
Win-back — re-engage churned customers 30-90 days after churn.

2-step sequence:
  Step 1 (today): what changed since they left
  Step 2 (day 7): a new specific reason to return

Only run once per churned user per 90-day window.
Enqueues step 2 via TaskQueue with a 7-day delay flag.
"""

from __future__ import annotations

from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import SalesDB
from .mailer import SalesMailer, DUTCH_VOICE

logger = get_logger(__name__)

_WIN_BACK_COOLDOWN_DAYS = 90

_STEP1_SYSTEM = DUTCH_VOICE + """

You are writing the FIRST win-back email to a churned customer.
Focus on: what has specifically changed or improved since they left.
Be concrete — name a real feature or workflow improvement.
Do NOT be apologetic. Do NOT offer discounts in this email.
Max 4 sentences. Output body only.
"""

_STEP2_SYSTEM = DUTCH_VOICE + """

You are writing a FOLLOW-UP win-back email (second touch, 7 days after the first).
They haven't responded. This is the last touch.
Give them ONE new, specific reason to come back that wasn't in the first email.
End with a clear, low-friction ask (reply "interested" or book a 15-min call).
Max 3 sentences. Output body only.
"""

_SUBJECT_SYSTEM = "Write a concise email subject line only — no quotes, max 8 words. No clickbait."


class WinBack:

    def __init__(self, db: SalesDB, mailer: SalesMailer, cfg: dict[str, Any]) -> None:
        self._db = db
        self._mailer = mailer
        self._min_days = int(cfg.get("win_back_min_days", 30))
        self._max_days = int(cfg.get("win_back_max_days", 90))
        self._from_email = cfg.get("from_email", "")
        self._from_name = cfg.get("from_name", "Dutch")
        self._from_password = cfg.get("from_password", "")
        self._queue = TaskQueue()

    def run(self) -> dict[str, Any]:
        users = self._db.churned_in_window(self._min_days, self._max_days)
        sent = 0
        skipped = 0

        for user in users:
            user_id = str(user["id"])
            if self._db.win_back_sent_within(user_id, _WIN_BACK_COOLDOWN_DAYS):
                skipped += 1
                continue

            try:
                subject, body = self._generate_step1(user)
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
                    product=user["product"],
                    action_type="win_back",
                    user_id=user_id,
                    meta={"step": 1, "subject": subject},
                )

                # Enqueue step 2 for 7 days from now
                self._queue.push(
                    agent="sales",
                    payload={
                        "action": "win_back",
                        "sub_action": "step2",
                        "user_id": user_id,
                    },
                    priority=3,
                )
                sent += 1
                logger.info("win_back_step1_sent", user_id=user_id, product=user["product"])
            except Exception as exc:
                logger.error("win_back_failed", user_id=user_id, error=str(exc))

        return {"sent": sent, "skipped": skipped, "total_churned": len(users)}

    def send_step2(self, user_id: str) -> dict[str, Any]:
        user = self._db.get_user(user_id)
        if not user:
            return {"error": "user_not_found"}

        try:
            subject, body = self._generate_step2(user)
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
                product=user["product"],
                action_type="win_back",
                user_id=user_id,
                meta={"step": 2, "subject": subject},
            )
            logger.info("win_back_step2_sent", user_id=user_id)
            return {"sent": True, "step": 2}
        except Exception as exc:
            logger.error("win_back_step2_failed", user_id=user_id, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------

    def _generate_step1(self, user: dict[str, Any]) -> tuple[str, str]:
        name = user.get("company") or user.get("email", "").split("@")[0]
        prompt = (
            f"Recipient: {name}, churned from {user['product']} roughly {self._min_days}-{self._max_days} days ago\n"
            f"Their plan was: {user.get('plan', 'unknown')}\n\n"
            "Write the first win-back email. Focus on what has genuinely changed or improved "
            "since they left. Be specific to the product category."
        )
        return self._generate(prompt, _STEP1_SYSTEM)

    def _generate_step2(self, user: dict[str, Any]) -> tuple[str, str]:
        name = user.get("company") or user.get("email", "").split("@")[0]
        prompt = (
            f"Recipient: {name}, churned from {user['product']}. This is the final win-back touch.\n\n"
            "Give them one new specific reason to return. End with a low-friction ask."
        )
        return self._generate(prompt, _STEP2_SYSTEM)

    def _generate(self, prompt: str, system: str) -> tuple[str, str]:
        body = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=200,
            metadata={"caller": "sales.win_back"},
        ).content[0].text.strip()

        subject = llm.complete(
            messages=[{"role": "user", "content": f"Email body:\n{body}"}],
            system=_SUBJECT_SYSTEM,
            max_tokens=20,
            metadata={"caller": "sales.win_back.subject"},
        ).content[0].text.strip()

        return subject, body
