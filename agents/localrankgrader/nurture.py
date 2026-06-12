"""
Nurture sequence engine for LocalRankGrader leads.

5-step sequence triggered after report delivery:
  Step 1 (day 0):  report delivered (handled by reporter.py)
  Step 2 (day 3):  worst-scoring category deep-dive
  Step 3 (day 7):  industry social proof story
  Step 4 (day 14): objection handle — "I'm not technical"
  Step 5 (day 21): last call — close free access in 48h

Each email is LLM-generated using the lead's specific audit data.
Scheduling uses Celery eta so each send fires at the exact right datetime.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pathlib

from shared.config.settings import settings
from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

_FRAMEWORKS_MD = (
    pathlib.Path(__file__).parent.parent / "marketing" / "prompts" / "frameworks.md"
).read_text()

from .db import GraderDB
from .email import GraderMailer

logger = get_logger(__name__)

# Step index → delay in days after report delivery
_STEP_DELAYS = {2: 3, 3: 7, 4: 14, 5: 21}

# framework_mode per step: 2=grader_nurture, 3=sequence_early, 4=grader_nurture, 5=sequence_offer
_STEP_FRAMEWORK_MODE = {2: "grader_nurture", 3: "sequence_early", 4: "grader_nurture", 5: "sequence_offer"}

_STEP_PROMPTS = {
    2: """
Write a personal follow-up email (plain-text style, max 150 words) for a local business owner
who just received their Google Business Profile audit.

Business: {business_name}
Their worst-scoring category: {worst_category} — they scored {worst_score} out of {worst_max}.
Contact name: {contact_name}

Subject line: "Here's the #1 thing holding {business_name} back on Google"

The email should:
- Open with their specific pain point in that category
- Explain exactly what that low score costs them (missed calls, lost customers)
- Give ONE specific actionable tip they can do TODAY for free
- End with a soft CTA to start a LocalOutRank trial

Tone: direct, specific, empathetic — written by a local marketing expert, not a robot.
Output JSON: {{"subject": "...", "body_html": "...", "body_text": "..."}}
""",
    3: """
Write a social proof follow-up email (max 180 words) for a local business owner.

Business: {business_name}
Their industry / type: {business_type}
Their city / area: {city}
Their current Google score: {score}/100

Subject idea: "A {business_type} in {city} went from X reviews to Y in 30 days"

The email should:
- Tell a brief, specific story of a similar business that improved their GBP
- Quantify the outcome (more calls, higher ranking, more reviews)
- Subtly contrast their current situation with that success
- End with CTA: try LocalOutRank free for 14 days

Make the story believable and industry-specific.
Output JSON: {{"subject": "...", "body_html": "...", "body_text": "..."}}
""",
    4: """
Write an objection-handling email (max 150 words) for a local business owner
who hasn't started their LocalOutRank trial yet.

Business: {business_name}
Contact name: {contact_name}
Their Google score: {score}/100

Subject: "You don't need to be a tech person to use this"

The email should:
- Directly acknowledge the "I'm not tech-savvy" objection
- Explain that LocalOutRank does the work for them (set-it-and-forget-it)
- Give a concrete time estimate: "Takes 5 minutes to set up"
- Use plain language, zero jargon
- End with trial CTA

Output JSON: {{"subject": "...", "body_html": "...", "body_text": "..."}}
""",
    5: """
Write a "last call" urgency email (max 120 words) for a local business owner.

Business: {business_name}
Contact name: {contact_name}
Their Google score: {score}/100

Subject: "Closing {business_name}'s free report access in 48 hours"

The email should:
- Create genuine scarcity — this is actually the last email
- Remind them of their score and what it means
- State clearly that their free audit report access closes in 48 hours
- One strong CTA: claim LocalOutRank trial before access closes
- Short, direct, no fluff

Output JSON: {{"subject": "...", "body_html": "...", "body_text": "..."}}
""",
}


class NurtureSequencer:
    def __init__(self, db: GraderDB, mailer: GraderMailer, upgrade_nudge_threshold: int = 80) -> None:
        self._db = db
        self._mailer = mailer
        self._threshold = upgrade_nudge_threshold
        self._queue = TaskQueue()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def schedule_sequence(self, lead_id: str, audit_data: dict[str, Any]) -> None:
        """Schedule steps 2-5 as Celery tasks with eta after report delivery."""
        from agents.localrankgrader.tasks import send_nurture_step

        now = datetime.now(tz=timezone.utc)
        for step, delay_days in _STEP_DELAYS.items():
            eta = now + timedelta(days=delay_days)
            send_nurture_step.apply_async(
                kwargs={"lead_id": lead_id, "step": step},
                eta=eta,
            )
            logger.info("nurture_step_scheduled", lead_id=lead_id, step=step, eta=eta.isoformat())

    def send_step(self, lead_id: str, step: int) -> dict[str, Any]:
        """Execute a single nurture step. Called by the Celery task."""
        lead = self._db.get_lead(lead_id)
        if not lead:
            logger.warning("nurture_lead_not_found", lead_id=lead_id)
            return {"skipped": True, "reason": "lead_not_found"}

        if lead.get("trial_started_at"):
            logger.info("nurture_skip_already_converted", lead_id=lead_id)
            return {"skipped": True, "reason": "already_converted"}

        email_data = self._generate_step_email(step, lead)
        message_id = self._mailer.send_nurture(
            to_email=lead["email"],
            to_name=lead.get("contact_name") or "there",
            subject=email_data["subject"],
            body_html=email_data["body_html"],
            body_text=email_data["body_text"],
            lead_id=lead_id,
            step=step,
        )
        self._db.advance_sequence_step(lead_id)
        logger.info("nurture_step_sent", lead_id=lead_id, step=step, email=lead["email"])
        return {"sent": True, "step": step, "message_id": message_id}

    def handle_score_update(self, lead_id: str, new_score: int) -> None:
        """Check if lead should be escalated to sales upgrade nudge."""
        if new_score >= self._threshold:
            lead = self._db.get_lead(lead_id)
            if lead and not lead.get("trial_started_at"):
                self._queue.push(
                    agent="forge",
                    payload={
                        "action": "lead_score_forge",
                        "lead_ids": [lead_id],
                        "source": "local_rank_grader",
                        "trigger": "upgrade_nudge",
                    },
                    priority=3,
                )
                logger.info("upgrade_nudge_dispatched", lead_id=lead_id, score=new_score)

    # ------------------------------------------------------------------
    # LLM email generation
    # ------------------------------------------------------------------

    def _generate_step_email(self, step: int, lead: dict[str, Any]) -> dict[str, Any]:
        template = _STEP_PROMPTS.get(step, "")
        if not template:
            return {"subject": "A note from LocalRankGrader", "body_html": "", "body_text": ""}

        category_scores: dict[str, int] = lead.get("category_scores") or {}
        worst_category = min(category_scores, key=lambda k: category_scores[k]) if category_scores else "completeness"
        weight_map = {"completeness": 25, "photos": 15, "reviews": 25, "posts": 10,
                      "qa": 5, "services": 5, "keywords": 10, "citations": 5}

        raw_places = lead.get("raw_places_data") or {}
        types_list = raw_places.get("types") or []
        business_type = types_list[0].replace("_", " ").title() if types_list else "local business"
        address = raw_places.get("formatted_address") or ""
        city = address.split(",")[1].strip() if "," in address else "your area"

        prompt = template.format(
            business_name=lead["business_name"],
            contact_name=lead.get("contact_name") or "there",
            score=lead["overall_score"],
            worst_category=worst_category.replace("_", " ").title(),
            worst_score=category_scores.get(worst_category, 0),
            worst_max=weight_map.get(worst_category, 10),
            business_type=business_type,
            city=city,
        )

        framework_mode = _STEP_FRAMEWORK_MODE.get(step, "sequence_early")
        system = (
            "You are a direct-response email copywriter. Output only valid JSON.\n\n"
            "## Copywriting Frameworks Reference\n\n" + _FRAMEWORKS_MD + "\n\n"
            f"Active framework_mode: {framework_mode}"
        )
        raw = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=600,
            metadata={"caller": "localrankgrader.nurture", "framework_mode": framework_mode},
        )
        block = raw.content[0]
        text = block.text.strip() if hasattr(block, "text") else ""
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
            text = text.rstrip("`").strip()
        try:
            return json.loads(text)
        except Exception:
            return {
                "subject": f"A note about {lead['business_name']}'s Google presence",
                "body_html": f"<p>{text}</p>",
                "body_text": text,
            }
