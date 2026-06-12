"""
Lead engagement scorer.

Scoring rules:
  +10 per email open         (capped at 3 opens = +30 max)
  +40 for email reply
  +20 per link click         (tracked via redirect URL in future)
  +5  per additional open beyond cap
  -20 if no engagement after 3 steps (mark COLD)
  >=60 → HOT — escalate to outreach agent queue

Updates forge_leads.score and syncs to Twenty CRM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

if TYPE_CHECKING:
    from .crm import TwentyCRMClient
    from .db import ForgeDB

logger = get_logger(__name__)


class LeadScorer:
    def __init__(
        self,
        db: "ForgeDB",
        crm: "TwentyCRMClient",
        hot_threshold: int = 60,
    ) -> None:
        self._db = db
        self._crm = crm
        self._hot_threshold = hot_threshold
        self._queue = TaskQueue()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def score_leads(self, lead_ids: list[str] | None = None) -> dict[str, Any]:
        """Score a list of leads (or all active leads if not specified)."""
        if lead_ids is None:
            leads = self._db.get_leads_by_product("", status="CONTACTED", limit=1000)
        else:
            leads = self._db.get_leads_by_list(lead_ids)

        scored, upgraded = 0, 0
        for lead in leads:
            lid = str(lead["id"])
            new_score = self._compute_score(lead)
            if new_score == lead.get("score", 0):
                continue

            self._db.update_lead_score(lid, new_score)
            scored += 1

            # Sync score to CRM
            if lead.get("crm_id"):
                self._crm.update_score(str(lead["crm_id"]), new_score)

            # Promote COLD leads that went below 0
            if new_score < 0 and lead["status"] not in ("COLD", "UNSUBSCRIBED", "BOUNCED"):
                self._db.update_lead_status(lid, "COLD")
                logger.info("lead_marked_cold", lead_id=lid, score=new_score)

            # Escalate HOT leads
            if new_score >= self._hot_threshold and lead["status"] not in ("HOT", "CONVERTED"):
                self._escalate_hot(lead, new_score)
                upgraded += 1

        return {"scored": scored, "upgraded_to_hot": upgraded}

    def compute_score(self, lead: dict[str, Any]) -> int:
        return self._compute_score(lead)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_score(self, lead: dict[str, Any]) -> int:
        eng = self._db.get_lead_engagement(str(lead["id"]))

        opens = eng["opens"]
        replies = eng["replies"]
        sends = eng["sends"]
        unsubscribes = eng["unsubscribes"]

        if unsubscribes > 0:
            return -100  # immediately disqualify

        score = 0
        # Opens: +10 each (cap at 3), +5 for each beyond cap
        capped_opens = min(opens, 3)
        extra_opens = max(opens - 3, 0)
        score += capped_opens * 10 + extra_opens * 5

        # Replies: +40
        score += min(replies, 1) * 40

        # No engagement after 3+ steps
        if sends >= 3 and opens == 0 and replies == 0:
            score -= 20

        return score

    def _escalate_hot(self, lead: dict[str, Any], score: int) -> None:
        lid = str(lead["id"])
        self._db.update_lead_status(lid, "HOT")
        if lead.get("crm_id"):
            self._crm.update_status(str(lead["crm_id"]), "HOT")

        self._queue.push(
            agent="outreach",
            payload={
                "action": "handle_hot_lead",
                "lead_id": lid,
                "lead_email": lead.get("email"),
                "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                "company": lead.get("company"),
                "score": score,
                "research_notes": lead.get("research_notes", ""),
                "source": "forge",
            },
            priority=1,
        )
        logger.info("lead_escalated_hot", lead_id=lid, score=score, email=lead.get("email"))
