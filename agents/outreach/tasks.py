"""Celery tasks for the outreach agent."""

from __future__ import annotations

from shared.celery_app import app


@app.task(name="agents.outreach.tasks.dispatch_due_sequences", ignore_result=True)
def dispatch_due_sequences() -> None:
    """Enqueue all outreach sequence steps whose next_action_at is past."""
    from agents._base import AgentConfig
    from agents.outreach.db import OutreachDB
    from agents.outreach.sequence_mgr import SequenceManager

    db = OutreachDB()
    mgr = SequenceManager(db)
    result = mgr.dispatch_due()
    from shared.logger import get_logger
    get_logger(__name__).info("dispatch_due_sequences_ran", **result)
