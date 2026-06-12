"""
BaseAgent — abstract base class for all Vance agents.

Adding a new agent: subclass BaseAgent, implement handle() and health_check(),
point it at a config.yaml. Nothing else needs to change.
"""

from __future__ import annotations

import abc
import json
import threading
import time
from typing import Any

import redis

from shared.config.settings import settings
from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue
from shared.types import Task, TaskResult

from .config import AgentConfig
from .events import EVENTS_CHANNEL, AgentEvent, EventPayload

RESPONSES_CHANNEL = "vance:responses"

logger = get_logger(__name__)


class BaseAgent(abc.ABC):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        self.agent_name = agent_name
        self.config = config
        self._queue = TaskQueue()
        self._redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            db=settings.REDIS_DB_QUEUE,
            decode_responses=True,
        )

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def handle(self, task: Task) -> TaskResult:
        """Process one task and return a result."""
        ...

    @abc.abstractmethod
    def health_check(self) -> bool:
        """Return True if the agent and its dependencies are reachable."""
        ...

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, stop_event: threading.Event | None = None) -> None:
        """Block and process tasks until stop_event is set (or forever)."""
        logger.info("agent_started", agent=self.agent_name)
        interval = int(self.config.poll_interval_seconds)

        while stop_event is None or not stop_event.is_set():
            try:
                raw = self._queue.pop(timeout=interval)
                if raw is None:
                    continue
                self._process_task(raw)
            except Exception as exc:
                logger.error("run_loop_error", agent=self.agent_name, error=str(exc))
                time.sleep(interval)

    def _process_task(self, raw: dict[str, Any]) -> None:
        task = Task.from_queue_dict(raw)
        self.emit(AgentEvent.TASK_STARTED, task_id=task.id)
        try:
            result = self.handle(task)
            self._queue.ack(task.id)
            self.emit(AgentEvent.TASK_COMPLETE, task_id=task.id, data={"output": str(result.output)})
            logger.info("task_complete", agent=self.agent_name, task_id=task.id)
        except Exception as exc:
            self._queue.nack(task.id)
            self.emit(AgentEvent.TASK_FAILED, task_id=task.id, data={"error": str(exc)})
            logger.error("task_failed", agent=self.agent_name, task_id=task.id, error=str(exc))

    # ------------------------------------------------------------------
    # Provided helpers
    # ------------------------------------------------------------------

    def ask_llm(
        self,
        prompt: str,
        system_prompt: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> str:
        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": prompt})
        response = llm.complete(
            messages=messages,
            system=system_prompt or self.config.llm_system_prompt or None,
            metadata={"caller": self.agent_name},
        )
        return response.content[0].text

    def emit(
        self,
        event_type: AgentEvent,
        task_id: str | None = None,
        message: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        payload = EventPayload(
            event_type=event_type,
            agent=self.agent_name,
            task_id=task_id,
            message=message,
            data=data or {},
        )
        self._redis.publish(EVENTS_CHANNEL, payload.model_dump_json())

    def report(self, message: str) -> None:
        self._redis.publish(
            RESPONSES_CHANNEL,
            json.dumps({"agent": self.agent_name, "message": message}),
        )

    def get_config(self, key: str) -> Any:
        return self.config.custom.get(key)
