"""BriefCompiler — assembles daily brief from cross-agent data and LLM narrative."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import ReportingDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are a chief of staff writing a concise daily operations brief. "
    "Given cross-agent data sections, produce a structured markdown brief. "
    "Start with a 2-sentence executive summary. Then one section per data group, "
    "using bullet points. Flag anything requiring immediate action with ⚠️. "
    "Keep the entire brief under 400 words."
)


class BriefCompiler:

    def __init__(self, db: ReportingDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def compile_daily(self, brief_date: str | None = None) -> dict[str, Any]:
        today = brief_date or date.today().isoformat()
        items = self._db.get_brief_items(brief_date=today)

        if not items:
            content = f"# Daily Brief — {today}\n\nNo items received today."
        else:
            sections: dict[str, list] = {}
            for item in items:
                sec = item["section"]
                sections.setdefault(sec, []).append(item["data"])

            prompt = f"Date: {today}\n\nData sections:\n{json.dumps(sections, default=str, indent=2)}"
            resp = llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system=_SYSTEM,
                max_tokens=800,
            )
            content = resp.content[0].text.strip()

        recipients = self._cfg.get("daily_recipients", [])
        digest_id = self._db.save_digest(period="daily", period_date=today, content=content, recipients=recipients)

        if recipients:
            self._send_email(subject=f"Vance Daily Brief — {today}", body=content, recipients=recipients)
            self._db.mark_digest_sent(period="daily", period_date=today)

        logger.info("daily_brief_compiled", date=today, sections=len(sections) if items else 0)
        return {"period": "daily", "date": today, "digest_id": digest_id, "sections": len(items), "content": content}

    def compile_weekly(self, from_date: str, to_date: str) -> dict[str, Any]:
        items = self._db.get_brief_items_range(from_date=from_date, to_date=to_date)

        sections: dict[str, list] = {}
        for item in items:
            sections.setdefault(item["section"], []).append(item["data"])

        prompt = f"Week: {from_date} to {to_date}\n\nAll data:\n{json.dumps(sections, default=str, indent=2)}"
        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM,
            max_tokens=1200,
        )
        content = resp.content[0].text.strip()

        recipients = self._cfg.get("weekly_recipients", self._cfg.get("daily_recipients", []))
        digest_id = self._db.save_digest(period="weekly", period_date=to_date, content=content, recipients=recipients)

        if recipients:
            self._send_email(subject=f"Vance Weekly Digest — w/e {to_date}", body=content, recipients=recipients)
            self._db.mark_digest_sent(period="weekly", period_date=to_date)

        logger.info("weekly_digest_compiled", from_date=from_date, to_date=to_date)
        return {"period": "weekly", "from": from_date, "to": to_date, "digest_id": digest_id, "content": content}

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
            logger.info("digest_email_sent", recipients=len(recipients))
        except Exception as exc:
            logger.warning("digest_email_failed", error=str(exc))
