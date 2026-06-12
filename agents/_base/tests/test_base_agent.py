"""Tests for BaseAgent — queue polling, task dispatch, event emission."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch, call
from datetime import datetime

import pytest

from agents._base.agent import BaseAgent, RESPONSES_CHANNEL
from agents._base.config import AgentConfig
from agents._base.events import EVENTS_CHANNEL, AgentEvent
from shared.types import Task, TaskResult, AgentCapability


# ---------------------------------------------------------------------------
# Fixture: minimal concrete agent
# ---------------------------------------------------------------------------

class EchoAgent(BaseAgent):
    """Concrete agent that echoes the task payload action field."""

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action", "noop")
        return TaskResult(task_id=task.id, success=True, output=action)

    def health_check(self) -> bool:
        return True


RAW_TASK = {
    "id": "task-001",
    "agent": "marketing",
    "payload": {"action": "generate_copy"},
    "priority": 5,
    "created_at": datetime.utcnow().isoformat(),
}


@pytest.fixture()
def agent(mocker):
    config = AgentConfig(agent_name="echo", llm_system_prompt="You are helpful.")
    a = EchoAgent("echo", config)
    # Patch Redis to avoid real connection
    a._redis = MagicMock()
    mocker.patch.object(a._queue, "ack")
    mocker.patch.object(a._queue, "nack")
    return a


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProcessTask:
    def test_handle_is_called_and_ack_on_success(self, agent):
        agent._process_task(RAW_TASK)

        agent._queue.ack.assert_called_once_with("task-001")
        agent._queue.nack.assert_not_called()

    def test_task_complete_event_emitted(self, agent):
        agent._process_task(RAW_TASK)

        publish_calls = agent._redis.publish.call_args_list
        channels = [c.args[0] for c in publish_calls]
        assert EVENTS_CHANNEL in channels

        # The TASK_COMPLETE event payload should reference our task id
        complete_call = next(
            c for c in publish_calls
            if "task_complete" in c.args[1]
        )
        assert "task-001" in complete_call.args[1]

    def test_task_started_event_emitted_before_complete(self, agent):
        agent._process_task(RAW_TASK)

        payloads = [c.args[1] for c in agent._redis.publish.call_args_list]
        started_idx = next(i for i, p in enumerate(payloads) if "task_started" in p)
        complete_idx = next(i for i, p in enumerate(payloads) if "task_complete" in p)
        assert started_idx < complete_idx

    def test_nack_and_failed_event_on_handle_exception(self, agent, mocker):
        mocker.patch.object(agent, "handle", side_effect=RuntimeError("boom"))

        agent._process_task(RAW_TASK)

        agent._queue.nack.assert_called_once_with("task-001")
        agent._queue.ack.assert_not_called()

        payloads = [c.args[1] for c in agent._redis.publish.call_args_list]
        assert any("task_failed" in p for p in payloads)
        assert any("boom" in p for p in payloads)


class TestRunLoop:
    def test_run_processes_task_then_stops(self, agent, mocker):
        stop = threading.Event()

        call_count = 0

        def _pop(timeout=0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return RAW_TASK
            stop.set()
            return None

        mocker.patch.object(agent._queue, "pop", side_effect=_pop)

        agent.run(stop_event=stop)

        agent._queue.ack.assert_called_once_with("task-001")


class TestHelpers:
    def test_get_config_returns_custom_value(self):
        config = AgentConfig(
            agent_name="test",
            custom={"api_key": "secret123"},
        )
        a = EchoAgent("test", config)
        assert a.get_config("api_key") == "secret123"
        assert a.get_config("missing") is None

    def test_report_publishes_to_responses_channel(self, agent):
        agent.report("hello from agent")

        agent._redis.publish.assert_called_once()
        channel, payload = agent._redis.publish.call_args.args
        assert channel == RESPONSES_CHANNEL
        assert "hello from agent" in payload
        assert "echo" in payload

    def test_health_check(self, agent):
        assert agent.health_check() is True

    def test_ask_llm_delegates_to_shared_llm(self, agent, mocker):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Generated copy here")]
        mock_complete = mocker.patch("agents._base.agent.llm.complete", return_value=mock_response)

        result = agent.ask_llm("Write a tagline", system_prompt="Be creative")

        assert result == "Generated copy here"
        mock_complete.assert_called_once()
        call_kwargs = mock_complete.call_args.kwargs
        assert call_kwargs["system"] == "Be creative"
        assert call_kwargs["messages"][-1] == {"role": "user", "content": "Write a tagline"}


class TestAgentConfig:
    def test_defaults(self):
        cfg = AgentConfig(agent_name="mkt")
        assert cfg.enabled is True
        assert cfg.poll_interval_seconds == 2.0
        assert cfg.max_retries == 3
        assert cfg.custom == {}

    def test_custom_fields(self):
        cfg = AgentConfig(agent_name="mkt", custom={"foo": 1})
        assert cfg.custom["foo"] == 1
