"""Handle a new GBP audit submission from the LocalRankGrader.com public form."""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

logger = get_logger(__name__)

_queue = TaskQueue()


def handle_grader_submit(payload: dict[str, Any]) -> dict[str, Any]:
    business_name = payload.get("business_name", "").strip()
    contact_email = payload.get("contact_email", "").strip()

    if not business_name or not contact_email:
        return {"status": "error", "reason": "business_name and contact_email are required"}

    task_id = _queue.push(
        agent="local_rank_grader",
        payload={
            "action": "run_audit",
            "business_name": business_name,
            "contact_email": contact_email,
            "contact_name": payload.get("contact_name"),
            "place_id": payload.get("place_id"),
            "address": payload.get("address"),
            "keyword": payload.get("keyword"),
        },
        priority=5,
    )
    logger.info("grader_submit_queued", business=business_name, email=contact_email, task_id=task_id)
    return {"status": "queued", "task_id": task_id}
