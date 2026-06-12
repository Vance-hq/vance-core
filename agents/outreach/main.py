"""
Outreach agent — 1:1 personalised outreach across LinkedIn and email.

Actions:
  linkedin_connect   — send a connection request with a personalised note
  linkedin_message   — send a DM to an existing connection (48h throttle)
  email_followup     — reply to an INTERESTED/QUESTION reply in Dutch's voice
  lead_score         — score a contact on engagement signals → HOT/WARM/COLD
  contact_research   — web search + LLM brief for a contact, stored in contacts table
  sequence_manager   — enroll/advance/dispatch 1:1 outreach sequences
"""

from __future__ import annotations

import os
from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.db.client import get_db
from shared.llm.client import llm
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .db import OutreachDB
from .emailer import FollowupMailer
from .linkedin import LinkedInClient
from .researcher import ContactResearcher
from .scorer import ContactScorer
from .sequence_mgr import SequenceManager

logger = get_logger(__name__)

_LINKEDIN_NOTE_SYSTEM = """You are Dutch — a 26-year trades veteran who built and sold two SaaS businesses.
Write a LinkedIn connection note. Rules:
- Max 280 characters (hard limit — count carefully)
- Peer-to-peer tone, no pitch
- One specific reason for connecting based on their work
- End with your first name only: "— Dutch"
- Output the note text only, nothing else
"""

_LINKEDIN_MESSAGE_SYSTEM = """You are Dutch — a 26-year trades veteran who built and sold two SaaS businesses.
Write a LinkedIn DM. Rules:
- Max 300 characters
- Reference the sequence context: what you do, why it's relevant to them specifically
- Single specific ask (a reply, a call, a quick look at something)
- No filler. No "hope this finds you well". No pitch deck.
- Output the message text only, nothing else
"""

_NO_LINKEDIN_PRODUCTS = {"trusted_plumbing"}


class OutreachAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = OutreachDB()
        self._researcher = ContactResearcher()
        self._scorer = ContactScorer(
            weights=cfg.get("scoring_weights"),
            tiers=cfg.get("scoring_tiers"),
        )
        self._mailer = FollowupMailer()
        self._seq = SequenceManager(self._db)
        self._linkedin: LinkedInClient | None = None  # lazy — not all tasks need it

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "linkedin_connect": lambda: self._linkedin_connect(p),
            "linkedin_message": lambda: self._linkedin_message(p),
            "email_followup":   lambda: self._email_followup(p),
            "lead_score":       lambda: self._lead_score(p),
            "contact_research": lambda: self._contact_research(p),
            "sequence_manager": lambda: self._sequence_manager(p),
        }

        handler = dispatch.get(action)
        if not handler:
            raise ValueError(f"Unknown outreach action: {action}")

        logger.info("outreach_task_started", action=action, task_id=task.id)
        output = handler()

        # Auto-advance sequence when a sequenced step reports success
        if p.get("_from_sequence") and output.get("sent") is True:
            contact_id = p.get("contact_id", "")
            product = p.get("product", "")
            if contact_id:
                self._seq.complete_step(contact_id, product)

        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM contacts LIMIT 1")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Action: linkedin_connect
    # ------------------------------------------------------------------

    def _linkedin_connect(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required payload keys:
          contact_id, product, linkedin_url, name, company, role
        Optional:
          reason_for_connecting, research_notes
        """
        contact_id = p["contact_id"]
        product = p.get("product", "")

        if product in _NO_LINKEDIN_PRODUCTS:
            return {"sent": False, "reason": "linkedin_disabled_for_product"}

        if self._db.is_unsubscribed(contact_id):
            return {"sent": False, "reason": "contact_unsubscribed"}

        if self._db.linkedin_connect_sent(contact_id):
            return {"sent": False, "reason": "already_sent_connect_request"}

        note_prompt = (
            f"Name: {p.get('name', '')}\n"
            f"Company: {p.get('company', '')}\n"
            f"Role: {p.get('role', '')}\n"
            f"Reason: {p.get('reason_for_connecting', '')}\n"
            f"Research notes: {p.get('research_notes', '')}"
        )
        note = llm.complete(
            messages=[{"role": "user", "content": note_prompt}],
            system=_LINKEDIN_NOTE_SYSTEM,
            max_tokens=80,
            metadata={"caller": "outreach.linkedin_connect"},
        ).content[0].text.strip()
        note = note[: int(self.get_config("linkedin_note_max_chars") or 280)]

        result = self._get_linkedin().send_connection_request(p["linkedin_url"], note)
        if result.get("sent"):
            self._db.log_linkedin_action(contact_id, "connect", note)

        return result

    # ------------------------------------------------------------------
    # Action: linkedin_message
    # ------------------------------------------------------------------

    def _linkedin_message(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required payload keys:
          contact_id, linkedin_id, product
        Optional:
          sequence_step, context, name, company, role, research_notes
        """
        contact_id = p["contact_id"]
        product = p.get("product", "")

        if product in _NO_LINKEDIN_PRODUCTS:
            return {"sent": False, "reason": "linkedin_disabled_for_product"}

        if self._db.is_unsubscribed(contact_id):
            return {"sent": False, "reason": "contact_unsubscribed"}

        hours_since = self._db.hours_since_last_linkedin_message(contact_id)
        if hours_since < 48:
            return {"sent": False, "reason": "48h_throttle", "hours_since_last": round(hours_since, 1)}

        msg_prompt = (
            f"Contact: {p.get('name', '')} at {p.get('company', '')}, {p.get('role', '')}\n"
            f"Product: {product}\n"
            f"Sequence step: {p.get('sequence_step', 1)}\n"
            f"Context: {p.get('context', p.get('research_notes', ''))}"
        )
        message = llm.complete(
            messages=[{"role": "user", "content": msg_prompt}],
            system=_LINKEDIN_MESSAGE_SYSTEM,
            max_tokens=100,
            metadata={"caller": "outreach.linkedin_message"},
        ).content[0].text.strip()

        result = self._get_linkedin().send_direct_message(p["linkedin_id"], message)
        if result.get("sent"):
            self._db.log_linkedin_action(contact_id, "message", message)

        return result

    # ------------------------------------------------------------------
    # Action: email_followup
    # ------------------------------------------------------------------

    def _email_followup(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required payload keys:
          contact_id, product, original_email, their_reply
        Optional:
          from_email, from_name, from_password (fall back to config / env)
        """
        contact_id = p["contact_id"]
        contact = self._db.get_contact(contact_id)
        if not contact:
            return {"sent": False, "reason": "contact_not_found"}

        if self._db.is_unsubscribed(contact_id):
            return {"sent": False, "reason": "contact_unsubscribed"}

        if not contact.get("email"):
            return {"sent": False, "reason": "no_email_on_contact"}

        cfg = self.config.custom
        from_email = p.get("from_email") or cfg.get("outreach_from_email") or os.environ.get("OUTREACH_FROM_EMAIL", "")
        from_name = p.get("from_name") or cfg.get("outreach_from_name") or "Dutch"
        from_password = p.get("from_password") or cfg.get("outreach_from_password") or os.environ.get("OUTREACH_FROM_PASSWORD", "")

        return self._mailer.send_followup(
            contact=contact,
            original_email=p.get("original_email", ""),
            their_reply=p.get("their_reply", ""),
            from_email=from_email,
            from_name=from_name,
            from_password=from_password,
            product=p.get("product", ""),
        )

    # ------------------------------------------------------------------
    # Action: lead_score
    # ------------------------------------------------------------------

    def _lead_score(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required payload keys:
          contact_id, product
        Optional signal inputs (all default to 0):
          role, company_size, email_opens, email_clicks, replies, linkedin_activity
        """
        contact_id = p["contact_id"]
        contact = self._db.get_contact(contact_id)
        if not contact:
            return {"error": "contact_not_found"}

        result = self._scorer.score(
            contact_id=contact_id,
            product=p.get("product", contact.get("product", "")),
            role=p.get("role", contact.get("role", "")),
            company_size=p.get("company_size", ""),
            email_opens=int(p.get("email_opens", 0)),
            email_clicks=int(p.get("email_clicks", 0)),
            replies=int(p.get("replies", 0)),
            linkedin_activity=int(p.get("linkedin_activity", 0)),
        )

        self._db.update_contact_score(
            contact_id,
            result["score"],
            result["tier"],
            result["recommended_next_action"],
        )
        return result

    # ------------------------------------------------------------------
    # Action: contact_research
    # ------------------------------------------------------------------

    def _contact_research(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required payload keys:
          name, company, product
        Optional:
          contact_id, role, website
        If contact_id provided, stores brief in contacts.research_notes.
        """
        result = self._researcher.research(
            name=p["name"],
            company=p["company"],
            product=p.get("product", ""),
            role=p.get("role"),
            website=p.get("website"),
        )

        contact_id = p.get("contact_id")
        if contact_id and result.get("brief"):
            self._db.update_research_notes(contact_id, result["brief"])

        return result

    # ------------------------------------------------------------------
    # Action: sequence_manager
    # ------------------------------------------------------------------

    def _sequence_manager(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required payload keys:
          sub_action: "start" | "complete_step" | "opt_out" | "dispatch_due"
        For start/complete_step/opt_out:
          contact_id: str
        For start:
          product: str
        """
        sub = p.get("sub_action", "start")
        contact_id = p.get("contact_id", "")
        product = p.get("product", "")

        if sub == "start":
            return self._seq.start(contact_id, product)
        if sub == "complete_step":
            return self._seq.complete_step(contact_id, product)
        if sub == "opt_out":
            return self._seq.opt_out(contact_id)
        if sub == "dispatch_due":
            return self._seq.dispatch_due()

        return {"error": f"unknown sub_action: {sub}"}

    # ------------------------------------------------------------------

    def _get_linkedin(self) -> LinkedInClient:
        if self._linkedin is None:
            self._linkedin = LinkedInClient()
        return self._linkedin


if __name__ == "__main__":
    config = AgentConfig.load("outreach")
    OutreachAgent("outreach", config).run()
