"""
Sequence manager — drives 1:1 outreach sequences per contact.

Default step schedule:
  Step 0: linkedin_connect   day 0
  Step 1: linkedin_message   day 3
  Step 2: email_followup     day 7  (first unsolicited email)
  Step 3: email_followup     day 14 (final bump)

For trusted_plumbing: LinkedIn steps are skipped (step 0 → step 2 immediately).

The manager enqueues the next step task into TaskQueue so the agent
processes it at the correct time without requiring a cron job.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import OutreachDB

logger = get_logger(__name__)

_STEPS: list[dict[str, Any]] = [
    {"action": "linkedin_connect", "delay_days": 0},
    {"action": "linkedin_message", "delay_days": 3},
    {"action": "email_followup",   "delay_days": 7},
    {"action": "email_followup",   "delay_days": 14},
]

# Products that skip LinkedIn — go straight to email
_NO_LINKEDIN_PRODUCTS = {"trusted_plumbing"}


class SequenceManager:

    def __init__(self, db: OutreachDB) -> None:
        self._db = db
        self._queue = TaskQueue()

    def start(self, contact_id: str, product: str) -> dict[str, Any]:
        """Enroll a contact into a sequence, or resume if already enrolled."""
        seq_id = self._db.upsert_sequence(contact_id, product)
        seq = self._db.get_sequence(contact_id)

        if seq["status"] in ("OPTED_OUT", "COMPLETE"):
            return {"status": seq["status"], "contact_id": contact_id}

        # Determine first valid step (skip LinkedIn for certain products)
        first_step = self._first_step(product)
        if seq["current_step"] == 0 and seq["status"] == "ACTIVE":
            self._enqueue_step(contact_id, product, first_step, delay_days=0)

        logger.info("sequence_started", contact_id=contact_id, product=product, first_step=first_step)
        return {"status": "started", "sequence_id": seq_id, "first_step": first_step}

    def complete_step(self, contact_id: str, product: str) -> dict[str, Any]:
        """Mark current step done and enqueue the next one, if any."""
        seq = self._db.get_sequence(contact_id)
        if not seq or seq["status"] != "ACTIVE":
            return {"status": seq["status"] if seq else "not_found", "contact_id": contact_id}

        current = seq["current_step"]
        next_step = self._next_valid_step(current + 1, product)

        if next_step is None:
            self._db.complete_sequence(contact_id)
            logger.info("sequence_complete", contact_id=contact_id)
            return {"status": "complete", "contact_id": contact_id}

        step_def = _STEPS[next_step]
        delay = step_def["delay_days"] - _STEPS[current]["delay_days"]
        next_at = datetime.now(timezone.utc) + timedelta(days=max(delay, 0))

        self._db.advance_sequence(contact_id, next_step, next_at)
        self._enqueue_step(contact_id, product, next_step, delay_days=max(delay, 0))

        logger.info("sequence_advanced", contact_id=contact_id, next_step=next_step, delay_days=delay)
        return {"status": "advanced", "next_step": next_step, "next_action_at": next_at.isoformat()}

    def opt_out(self, contact_id: str) -> dict[str, Any]:
        self._db.opt_out_sequence(contact_id)
        self._db.mark_unsubscribed(contact_id)
        return {"status": "opted_out", "contact_id": contact_id}

    def dispatch_due(self) -> dict[str, Any]:
        """Enqueue all sequences whose next_action_at is past. Called by Celery beat."""
        due = self._db.due_sequences()
        enqueued = 0
        for row in due:
            step_def = _STEPS[row["current_step"]]
            product = row["product"]
            contact_id = str(row["contact_id"])

            self._queue.push(
                agent="outreach",
                payload={
                    "action": step_def["action"],
                    "contact_id": contact_id,
                    "product": product,
                    "linkedin_url": row.get("linkedin_url", ""),
                    "email": row.get("email", ""),
                    "name": row.get("name", ""),
                    "company": row.get("company", ""),
                    "role": row.get("role", ""),
                    "research_notes": row.get("research_notes", ""),
                    "_from_sequence": True,
                },
            )
            enqueued += 1

        return {"enqueued": enqueued}

    # ------------------------------------------------------------------

    def _enqueue_step(
        self,
        contact_id: str,
        product: str,
        step_idx: int,
        delay_days: int,
    ) -> None:
        step_def = _STEPS[step_idx]
        contact = self._db.get_contact(contact_id)
        if not contact:
            return

        self._queue.push(
            agent="outreach",
            payload={
                "action": step_def["action"],
                "contact_id": contact_id,
                "product": product,
                "linkedin_url": contact.get("linkedin_url", ""),
                "email": contact.get("email", ""),
                "name": contact.get("name", ""),
                "company": contact.get("company", ""),
                "role": contact.get("role", ""),
                "research_notes": contact.get("research_notes", ""),
                "_from_sequence": True,
                "_delay_days": delay_days,
            },
        )

    @staticmethod
    def _first_step(product: str) -> int:
        if product in _NO_LINKEDIN_PRODUCTS:
            return 2  # skip to email
        return 0

    @staticmethod
    def _next_valid_step(candidate: int, product: str) -> int | None:
        while candidate < len(_STEPS):
            action = _STEPS[candidate]["action"]
            if product in _NO_LINKEDIN_PRODUCTS and "linkedin" in action:
                candidate += 1
                continue
            return candidate
        return None
