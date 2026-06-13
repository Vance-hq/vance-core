"""DailyBriefer — compiles and delivers Dutch's morning briefing via voice and email."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import ReportingDB

logger = get_logger(__name__)

_SECTIONS = ("revenue", "campaigns", "content", "product", "alerts", "general")

_SYSTEM = (
    "You are Vance, Dutch's AI chief of staff. "
    "Write a spoken morning briefing targeting exactly 90 seconds when read aloud (~225 words). "
    "Structure it as: greeting, then one sentence per section covering: "
    "REVENUE (MRR, signups, churn), CAMPAIGNS (emails sent, open rate, hot leads), "
    "CONTENT (published pieces, top performer), PRODUCT (deploys, bugs, P0/P1 open), "
    "ALERTS (anything requiring immediate attention). "
    "Speak directly to Dutch. Be specific with numbers. Flag urgent items clearly. "
    "End with one clear priority action for the day."
)


class DailyBriefer:

    def __init__(self, db: ReportingDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def compile(self, brief_date: str | None = None) -> dict[str, Any]:
        today = brief_date or date.today().isoformat()
        items = self._db.get_brief_items(brief_date=today)

        sections: dict[str, list] = {s: [] for s in _SECTIONS}
        for item in items:
            sec = item["section"] if item["section"] in _SECTIONS else "general"
            sections[sec].append(item["data"])

        # Remove empty sections for the prompt
        populated = {k: v for k, v in sections.items() if v}

        if not populated:
            content = (
                f"Good morning Dutch. It's {today}. "
                "No agent data has been received yet today — all systems are running but there's nothing to report. "
                "Consider triggering an analytics snapshot or checking that Celery beat tasks are firing."
            )
        else:
            prompt = (
                f"Date: {today}\n\n"
                f"Agent data sections:\n{json.dumps(populated, default=str, indent=2)}"
            )
            try:
                resp = llm.complete(
                    messages=[{"role": "user", "content": prompt}],
                    system=_SYSTEM,
                    max_tokens=600,
                )
                content = resp.content[0].text.strip()
            except Exception as exc:
                logger.warning("daily_briefer_llm_failed", error=str(exc))
                section_count = len(populated)
                content = (
                    f"Good morning Dutch. It's {today}. "
                    f"I have data from {section_count} section(s) but couldn't generate the full brief right now. "
                    "Please check the reporting logs."
                )

        report_id = self._db.save_report(
            report_type="daily_brief",
            content_text=content,
            period_date=today,
        )

        self._deliver_via_voice(content, today)

        recipients = self._cfg.get("daily_recipients", [])
        if recipients:
            self._send_email(
                subject=f"Vance Daily Brief — {today}",
                body=content,
                recipients=recipients,
            )

        logger.info("daily_brief_compiled", date=today, sections=len(populated))
        return {
            "report_id": report_id,
            "date": today,
            "sections": len(populated),
            "content": content,
        }

    def _deliver_via_voice(self, text: str, brief_date: str) -> None:
        try:
            TaskQueue().push(
                "voice",
                {
                    "action": "speak",
                    "text": text,
                    "priority": "high",
                    "source": "daily_brief",
                    "date": brief_date,
                },
            )
        except Exception as exc:
            logger.warning("daily_briefer_voice_failed", error=str(exc))

    def _send_email(self, subject: str, body: str, recipients: list[str]) -> None:
        try:
            import resend  # type: ignore
            api_key = self._cfg.get("resend_api_key", "")
            if not api_key:
                return
            resend.api_key = api_key
            resend.Emails.send({
                "from": self._cfg.get("from_email", "vance@mail.vance.so"),
                "to": recipients,
                "subject": subject,
                "text": body,
            })
            logger.info("daily_brief_email_sent", recipients=len(recipients))
        except Exception as exc:
            logger.warning("daily_brief_email_failed", error=str(exc))
