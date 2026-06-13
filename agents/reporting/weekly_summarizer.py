"""WeeklySummarizer — week-over-week trend analysis with written report and voice delivery."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import ReportingDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are Vance, Dutch's AI chief of staff writing the weekly business review. "
    "Analyze the week's agent data and produce a structured Markdown report with these sections:\n"
    "1. **Executive Summary** — 3 sentences on overall performance\n"
    "2. **Week-over-Week Trends** — key metric movements with % changes where possible\n"
    "3. **Biggest Win** — the single most positive development this week\n"
    "4. **Biggest Problem** — the most significant issue or concern\n"
    "5. **One Recommendation** — the single highest-leverage action for next week\n\n"
    "Be specific with numbers. Flag anything requiring immediate attention with ⚠️."
)

_DEFAULT_REPORTS_DIR = "reports"
# Words per minute for spoken delivery — used to truncate the voice version
_WPM = 150
_VOICE_TARGET_WORDS = _WPM * 2  # ~2 minutes


class WeeklySummarizer:

    def __init__(self, db: ReportingDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def compile(self, from_date: str, to_date: str) -> dict[str, Any]:
        items = self._db.get_brief_items_range(from_date=from_date, to_date=to_date)

        sections: dict[str, list] = {}
        for item in items:
            sections.setdefault(item["section"], []).append(item["data"])

        prompt = (
            f"Week: {from_date} to {to_date}\n\n"
            f"All agent data:\n{json.dumps(sections, default=str, indent=2)}"
        )

        try:
            resp = llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system=_SYSTEM,
                max_tokens=1200,
            )
            content = resp.content[0].text.strip()
        except Exception as exc:
            logger.warning("weekly_summarizer_llm_failed", error=str(exc))
            content = (
                f"# Weekly Summary — {from_date} to {to_date}\n\n"
                f"Summary generation failed. {len(items)} data items were collected this week."
            )

        report_id = self._db.save_report(
            report_type="weekly_summary",
            content_text=content,
            period_date=to_date,
        )

        self._save_markdown(content=content, from_date=from_date, to_date=to_date)
        self._deliver_via_voice(content=content, from_date=from_date, to_date=to_date)

        logger.info("weekly_summary_compiled", from_date=from_date, to_date=to_date, items=len(items))
        return {
            "period": "weekly",
            "from": from_date,
            "to": to_date,
            "report_id": report_id,
            "items_processed": len(items),
            "content": content,
        }

    def _save_markdown(self, content: str, from_date: str, to_date: str) -> None:
        reports_dir = Path(self._cfg.get("reports_dir", _DEFAULT_REPORTS_DIR))
        try:
            reports_dir.mkdir(parents=True, exist_ok=True)
            filename = f"weekly_{from_date}_to_{to_date}.md"
            (reports_dir / filename).write_text(content, encoding="utf-8")
            logger.info("weekly_report_saved", path=str(reports_dir / filename))
        except Exception as exc:
            logger.warning("weekly_report_save_failed", error=str(exc))

    def _deliver_via_voice(self, content: str, from_date: str, to_date: str) -> None:
        try:
            # Trim to ~2 minutes of speech — strip markdown headers for cleaner TTS
            words = [w for w in content.replace("#", "").split() if w]
            spoken = " ".join(words[:_VOICE_TARGET_WORDS])
            if len(words) > _VOICE_TARGET_WORDS:
                spoken += " … full report saved to the reports directory."

            TaskQueue().push(
                "voice",
                {
                    "action": "speak",
                    "text": spoken,
                    "priority": "normal",
                    "source": "weekly_summary",
                    "week": f"{from_date}/{to_date}",
                },
            )
        except Exception as exc:
            logger.warning("weekly_summarizer_voice_failed", error=str(exc))
