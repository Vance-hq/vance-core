"""
Session context — rolling in-memory log of the last N commands and their outcomes.

Passed to agents on dispatch so they have conversational continuity.
Not persisted — restarts clear history. Persistence can be added via Redis if needed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from shared.logger import get_logger
from .dispatcher import DispatchReceipt

logger = get_logger(__name__)

_MAX_ENTRIES = 10


@dataclass
class SessionEntry:
    intent_text: str
    intent_agent: str
    intent_action: str
    product: str | None
    receipt: dict[str, Any]
    outcome: str | None = None          # "success" | "failed" | "pending"
    outcome_detail: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class SessionContext:
    """Thread-safe (GIL-protected) rolling session log."""

    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._entries: deque[SessionEntry] = deque(maxlen=max_entries)

    def add(
        self,
        *,
        intent_text: str,
        intent_agent: str,
        intent_action: str,
        product: str | None,
        receipt: DispatchReceipt,
    ) -> None:
        entry = SessionEntry(
            intent_text=intent_text,
            intent_agent=intent_agent,
            intent_action=intent_action,
            product=product,
            receipt={
                "task_ids": receipt.task_ids,
                "agents": receipt.agents,
                "actions": receipt.actions,
                "estimated_completion": receipt.estimated_completion,
                "dispatched_at": receipt.dispatched_at,
            },
        )
        self._entries.append(entry)
        logger.debug("session_entry_added", agent=intent_agent, action=intent_action)

    def update_outcome(
        self, task_id: str, outcome: str, detail: str | None = None
    ) -> bool:
        """
        Mark the outcome of a completed task.
        Returns True if the task was found in session history, False otherwise.
        """
        for entry in reversed(self._entries):
            if task_id in entry.receipt.get("task_ids", []):
                entry.outcome = outcome
                entry.outcome_detail = detail
                logger.debug("session_outcome_updated", task_id=task_id, outcome=outcome)
                return True
        logger.warning("session_task_not_found", task_id=task_id)
        return False

    def get_context(self, n: int | None = None) -> list[dict[str, Any]]:
        """Return the last n entries as plain dicts (safe to serialise)."""
        entries = list(self._entries)
        if n is not None:
            entries = entries[-n:]
        return [
            {
                "intent_text": e.intent_text,
                "intent": f"{e.intent_agent}.{e.intent_action}",
                "product": e.product,
                "task_ids": e.receipt.get("task_ids", []),
                "outcome": e.outcome,
                "timestamp": e.timestamp,
            }
            for e in entries
        ]

    def __len__(self) -> int:
        return len(self._entries)
