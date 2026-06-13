"""Context brief builder — synthesizes a 5-sentence session brief from recent decisions."""

from __future__ import annotations

from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

logger = get_logger(__name__)

_BRIEF_SYSTEM = (
    "You are Vance, a business AI chief of staff. "
    "Synthesize the following recent decisions into exactly 5 concise sentences "
    "that give Dutch a clear picture of where everything stands right now. "
    "Be direct, specific, and mention concrete numbers where available. "
    "End with one sentence about the clearest next priority."
)

_FALLBACK_BRIEF = (
    "No decisions have been logged in the past 7 days. "
    "All systems are running but no major changes have been recorded. "
    "Consider triggering a competitor_activity_watch or analytics snapshot to surface current state. "
    "Review the Celery task schedule to confirm agents are executing. "
    "The top priority is ensuring Vance is capturing decisions as they happen."
)


class ContextBriefBuilder:

    def __init__(self, db: Any, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def build(self, days: int = 7) -> dict[str, Any]:
        decisions = self._db.list_recent_decisions(days=days, limit=30)

        if not decisions:
            brief = _FALLBACK_BRIEF
        else:
            lines = [
                f"- [{d.get('product', '?')}] {d['agent']}.{d['action']}: "
                f"{d.get('intent', '?')} → {d.get('outcome', '?')}"
                for d in decisions
            ]
            decisions_text = "\n".join(lines)
            try:
                resp = llm.complete(
                    messages=[{"role": "user", "content": f"Recent decisions (last {days} days):\n{decisions_text}"}],
                    system=_BRIEF_SYSTEM,
                    max_tokens=500,
                )
                brief = resp.content[0].text.strip()
            except Exception as exc:
                logger.warning("context_brief_llm_failed", error=str(exc))
                brief = f"Context brief unavailable. {len(decisions)} decisions logged in the last {days} days."

        self._deliver_via_voice(brief)
        return {"brief": brief, "decisions_included": len(decisions)}

    def _deliver_via_voice(self, brief: str) -> None:
        try:
            TaskQueue().push(
                "voice",
                {"action": "speak", "text": brief, "priority": "high", "source": "context_brief"},
            )
        except Exception as exc:
            logger.warning("context_brief_voice_delivery_failed", error=str(exc))
