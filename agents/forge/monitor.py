"""
Sequence monitor — metrics, reply classification, bounce alerting.

Reply pipeline:
  Mailcow Sieve filter → webhook POST → monitor.process_reply()
  → LLM classifies → INTERESTED escalates to outreach agent
                   → UNSUBSCRIBE removes lead from all sequences
                   → BOUNCE marks lead + pauses if rate > threshold
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

if TYPE_CHECKING:
    from .db import ForgeDB

logger = get_logger(__name__)

_CLASSIFY_PROMPT = """
Classify this cold email reply into exactly one category. Output ONLY the category name.

Categories:
  INTERESTED       — positive interest, wants to learn more, asking questions about the product
  NOT_INTERESTED   — polite decline, not the right fit
  UNSUBSCRIBE      — asks to be removed, stop emailing, unsubscribe
  OUT_OF_OFFICE    — automated away message
  QUESTION         — neutral question about the product/service
  BOUNCE           — delivery failure, mailbox full, invalid address

Reply:
---
{reply_body}
---

Category:""".strip()


class SequenceMonitor:
    def __init__(self, db: "ForgeDB", bounce_alert_threshold: float = 0.08) -> None:
        self._db = db
        self._bounce_threshold = bounce_alert_threshold
        self._queue = TaskQueue()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def monitor(self, sequence_id: str) -> dict[str, Any]:
        """Pull current metrics and trigger alerts / escalations as needed."""
        metrics = self._db.get_sequence_metrics(sequence_id)

        bounce_rate = metrics.get("bounce_rate", 0.0)
        if bounce_rate > self._bounce_threshold and metrics["sends"] >= 10:
            self._alert_high_bounce(sequence_id, bounce_rate)

        return {
            "sequence_id": sequence_id,
            **metrics,
        }

    def process_reply(self, send_id: str, reply_body: str) -> dict[str, Any]:
        """Classify a reply and act on it."""
        reply_type = self.classify_reply(reply_body)
        self._db.log_reply(send_id, reply_type, reply_body)

        send = self._db.get_lead_engagement(send_id)  # not ideal, but safe
        # Get lead_id from the send record
        from shared.db.client import get_db
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT lead_id, sequence_id FROM forge_sends WHERE id = %s", (send_id,))
                row = cur.fetchone()
        if not row:
            return {"reply_type": reply_type}

        lead_id, sequence_id = str(row[0]), str(row[1])

        if reply_type == "INTERESTED":
            self._escalate_to_outreach(lead_id, send_id, reply_body)
            self._pause_lead_in_sequence(lead_id)
            logger.info("reply_interested_escalated", lead_id=lead_id)

        elif reply_type == "UNSUBSCRIBE":
            self._db.update_lead_status(lead_id, "UNSUBSCRIBED")
            logger.info("reply_unsubscribed", lead_id=lead_id)

        elif reply_type == "BOUNCE":
            self._db.update_send_status(send_id, "BOUNCED")
            self._db.update_lead_status(lead_id, "BOUNCED")
            logger.info("reply_bounced", lead_id=lead_id)

        return {"reply_type": reply_type, "lead_id": lead_id, "sequence_id": sequence_id}

    def classify_reply(self, reply_body: str) -> str:
        """LLM-based reply classification. Falls back to keyword matching."""
        # Fast keyword pre-pass to skip LLM for obvious cases
        lower = reply_body.lower()
        if any(w in lower for w in ["unsubscribe", "remove me", "stop emailing", "opt out"]):
            return "UNSUBSCRIBE"
        if any(w in lower for w in ["out of office", "on vacation", "annual leave", "will be back"]):
            return "OUT_OF_OFFICE"
        if any(w in lower for w in ["mailer-daemon", "delivery failed", "mailbox full", "user unknown"]):
            return "BOUNCE"

        try:
            response = llm.complete(
                messages=[{
                    "role": "user",
                    "content": _CLASSIFY_PROMPT.format(reply_body=reply_body[:1_200]),
                }],
                max_tokens=10,
                metadata={"caller": "forge.monitor.classify"},
            )
            result = response.content[0].text.strip().upper()
            valid = {"INTERESTED", "NOT_INTERESTED", "UNSUBSCRIBE", "OUT_OF_OFFICE", "QUESTION", "BOUNCE"}
            return result if result in valid else "QUESTION"
        except Exception as exc:
            logger.warning("reply_classification_failed", error=str(exc))
            return "QUESTION"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _escalate_to_outreach(self, lead_id: str, send_id: str, reply_body: str) -> None:
        self._queue.push(
            agent="outreach",
            payload={
                "action": "handle_forge_reply",
                "lead_id": lead_id,
                "send_id": send_id,
                "reply_body": reply_body[:500],
                "source": "forge",
            },
            priority=1,
        )

    def _pause_lead_in_sequence(self, lead_id: str) -> None:
        self._db.update_lead_status(lead_id, "HOT")

    def _alert_high_bounce(self, sequence_id: str, bounce_rate: float) -> None:
        self._db.update_sequence_status(sequence_id, "PAUSED")
        logger.error(
            "forge_high_bounce_rate_paused",
            sequence_id=sequence_id,
            bounce_rate=round(bounce_rate, 3),
        )
