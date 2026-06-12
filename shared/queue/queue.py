"""Redis-backed task queue interface."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import redis

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)


class TaskQueue:
    """Push/pull task queue backed by Redis lists."""

    PENDING_KEY = "vance:queue:pending"
    PROCESSING_KEY = "vance:queue:processing"
    DEAD_LETTER_KEY = "vance:queue:dead"

    def __init__(self) -> None:
        self._r = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            db=settings.REDIS_DB_QUEUE,
            decode_responses=True,
        )

    def push(self, agent: str, payload: dict[str, Any], priority: int = 5) -> str:
        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "agent": agent,
            "payload": payload,
            "priority": priority,
            "created_at": datetime.utcnow().isoformat(),
        }
        self._r.lpush(self.PENDING_KEY, json.dumps(task))
        logger.debug("task_queued", task_id=task_id, agent=agent)
        return task_id

    def pop(self, timeout: int = 0) -> dict[str, Any] | None:
        result = self._r.brpop(self.PENDING_KEY, timeout=timeout)
        if result is None:
            return None
        _, raw = result
        task = json.loads(raw)
        self._r.hset(self.PROCESSING_KEY, task["id"], raw)
        return task

    def ack(self, task_id: str) -> None:
        self._r.hdel(self.PROCESSING_KEY, task_id)

    def nack(self, task_id: str) -> None:
        raw = self._r.hget(self.PROCESSING_KEY, task_id)
        if raw:
            self._r.lpush(self.DEAD_LETTER_KEY, raw)
            self._r.hdel(self.PROCESSING_KEY, task_id)
