"""
Dispatcher — takes routing results and writes tasks to the Redis queue.

Priority convention (lower int = higher priority, matches TaskQueue.push):
  CRITICAL = 1   security alerts, urgent sends
  HIGH     = 3   campaigns, deploys, connection sends
  NORMAL   = 5   reports, reads, analysis
  LOW      = 8   background / scheduled tasks
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from shared.logger import get_logger
from shared.queue import TaskQueue
from .router import RouteResult, UnknownIntentResult

logger = get_logger(__name__)

# Rough estimated completion windows by priority
_COMPLETION_ESTIMATES: dict[int, int] = {
    1: 5,    # CRITICAL → ~5 seconds
    3: 15,   # HIGH → ~15 seconds
    5: 60,   # NORMAL → ~1 minute
    8: 300,  # LOW → ~5 minutes
}


@dataclass
class DispatchReceipt:
    task_ids: list[str]
    agents: list[str]
    actions: list[str]
    estimated_completion: str | None   # ISO timestamp
    dispatched_at: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )


class Dispatcher:
    """Creates queue tasks from routing results and returns a receipt."""

    def __init__(self) -> None:
        self._queue = TaskQueue()

    def dispatch(
        self,
        routes: list[RouteResult],
        intent_payload: dict[str, Any],
    ) -> DispatchReceipt:
        """
        Push one task per route onto the queue.

        Args:
            routes:         List of RouteResult from the router.
            intent_payload: Serialised VoiceIntent fields to embed in each task.

        Returns:
            DispatchReceipt with all task_ids and estimated completion time.
        """
        task_ids: list[str] = []
        agents: list[str] = []
        actions: list[str] = []
        highest_priority = 5  # NORMAL default

        for route in routes:
            payload = {
                "action": route.action,
                **{k: v for k, v in intent_payload.items() if k != "session_context"},
            }

            task_id = self._queue.push(
                agent=route.agent,
                payload=payload,
                priority=route.priority,
            )

            task_ids.append(task_id)
            agents.append(route.agent)
            actions.append(route.action)

            if route.priority < highest_priority:
                highest_priority = route.priority

            logger.info(
                "task_dispatched",
                task_id=task_id,
                agent=route.agent,
                action=route.action,
                priority=route.priority,
                via=route.matched_via,
            )

        estimate_s = _COMPLETION_ESTIMATES.get(highest_priority, 60)
        estimated_completion = (
            (datetime.utcnow() + timedelta(seconds=estimate_s)).isoformat()
            if task_ids
            else None
        )

        return DispatchReceipt(
            task_ids=task_ids,
            agents=agents,
            actions=actions,
            estimated_completion=estimated_completion,
        )

    def dispatch_unknown(self, raw_text: str, result: UnknownIntentResult) -> None:
        """Log unknown intents for later review — does not queue a task."""
        logger.warning(
            "intent_unknown",
            raw_text=raw_text,
            best_pattern=result.best_pattern,
            best_score=result.best_score,
        )
