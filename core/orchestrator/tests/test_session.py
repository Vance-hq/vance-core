"""Tests for session context."""

import pytest
from unittest.mock import MagicMock

from core.orchestrator.session import SessionContext
from core.orchestrator.dispatcher import DispatchReceipt


def _make_receipt(task_id: str = "task-abc") -> DispatchReceipt:
    return DispatchReceipt(
        task_ids=[task_id],
        agents=["analytics"],
        actions=["revenue_report"],
        estimated_completion="2026-06-11T20:00:00",
    )


def test_add_and_get_context():
    ctx = SessionContext(max_entries=10)
    ctx.add(
        intent_text="what's our mrr",
        intent_agent="analytics",
        intent_action="revenue_report",
        product="starpio",
        receipt=_make_receipt("task-1"),
    )
    entries = ctx.get_context()
    assert len(entries) == 1
    assert entries[0]["intent"] == "analytics.revenue_report"
    assert entries[0]["product"] == "starpio"
    assert entries[0]["outcome"] is None


def test_maxlen_evicts_oldest():
    ctx = SessionContext(max_entries=3)
    for i in range(5):
        ctx.add(
            intent_text=f"command {i}",
            intent_agent="analytics",
            intent_action="revenue_report",
            product=None,
            receipt=_make_receipt(f"task-{i}"),
        )
    assert len(ctx) == 3
    entries = ctx.get_context()
    # Oldest two should be gone
    assert entries[0]["intent_text"] == "command 2"


def test_update_outcome_marks_entry():
    ctx = SessionContext()
    ctx.add(
        intent_text="deploy",
        intent_agent="dev",
        intent_action="deploy",
        product=None,
        receipt=_make_receipt("task-xyz"),
    )
    found = ctx.update_outcome("task-xyz", "success", "deployed to prod")
    assert found is True
    entries = ctx.get_context()
    assert entries[0]["outcome"] == "success"


def test_update_outcome_returns_false_for_unknown_task():
    ctx = SessionContext()
    found = ctx.update_outcome("nonexistent-task", "success")
    assert found is False


def test_get_context_n_limits_results():
    ctx = SessionContext()
    for i in range(8):
        ctx.add(
            intent_text=f"cmd {i}",
            intent_agent="analytics",
            intent_action="revenue_report",
            product=None,
            receipt=_make_receipt(f"t-{i}"),
        )
    assert len(ctx.get_context(3)) == 3
    assert len(ctx.get_context()) == 8
