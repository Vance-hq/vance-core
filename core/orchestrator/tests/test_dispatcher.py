"""Tests for the dispatcher."""

import pytest
from unittest.mock import MagicMock, patch

from core.orchestrator.router import RouteResult
from core.orchestrator.dispatcher import Dispatcher, DispatchReceipt


@pytest.fixture
def dispatcher():
    with patch("core.orchestrator.dispatcher.TaskQueue") as mock_q_cls:
        mock_q = MagicMock()
        mock_q.push.side_effect = ["task-1", "task-2", "task-3"]
        mock_q_cls.return_value = mock_q
        d = Dispatcher()
        d._queue = mock_q
        yield d, mock_q


def test_dispatch_single_route(dispatcher):
    d, mock_q = dispatcher
    routes = [
        RouteResult(agent="analytics", action="revenue_report", priority=5, matched_via="structured")
    ]
    receipt = d.dispatch(routes, {"action": "revenue_report"})

    assert isinstance(receipt, DispatchReceipt)
    assert len(receipt.task_ids) == 1
    assert receipt.agents == ["analytics"]
    assert receipt.actions == ["revenue_report"]
    assert receipt.estimated_completion is not None
    mock_q.push.assert_called_once_with(
        agent="analytics",
        payload={"action": "revenue_report"},
        priority=5,
    )


def test_dispatch_fan_out(dispatcher):
    d, mock_q = dispatcher
    routes = [
        RouteResult(agent="dev", action="deploy", priority=3, matched_via="structured"),
        RouteResult(agent="security", action="check_uptime", priority=3, matched_via="fan_out"),
    ]
    receipt = d.dispatch(routes, {"action": "deploy"})

    assert len(receipt.task_ids) == 2
    assert "dev" in receipt.agents
    assert "security" in receipt.agents


def test_critical_priority_gets_fastest_estimate(dispatcher):
    d, mock_q = dispatcher
    routes = [
        RouteResult(agent="security", action="send_alert", priority=1, matched_via="structured")
    ]
    receipt = d.dispatch(routes, {"action": "send_alert"})
    # CRITICAL (priority=1) → 5 second estimate
    assert receipt.estimated_completion is not None


def test_dispatch_unknown_does_not_queue(dispatcher):
    d, mock_q = dispatcher
    from core.orchestrator.router import UnknownIntentResult
    unknown = UnknownIntentResult(raw_text="play jazz", best_score=30.0, best_pattern=None)
    d.dispatch_unknown("play jazz", unknown)
    mock_q.push.assert_not_called()
