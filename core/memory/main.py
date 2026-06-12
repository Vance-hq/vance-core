"""Redis-backed session memory for the orchestrator."""

from __future__ import annotations

import json
from typing import Any

import redis

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)


class MemoryStore:
    """Stores and retrieves session context for the orchestrator."""

    def __init__(self) -> None:
        self._r = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            db=settings.REDIS_DB_SESSION,
            decode_responses=True,
        )

    def set(self, session_id: str, key: str, value: Any) -> None:
        field = f"{session_id}:{key}"
        self._r.setex(field, settings.REDIS_TTL_SESSION_S, json.dumps(value))

    def get(self, session_id: str, key: str) -> Any | None:
        field = f"{session_id}:{key}"
        raw = self._r.get(field)
        return json.loads(raw) if raw else None

    def clear(self, session_id: str) -> None:
        pattern = f"{session_id}:*"
        keys = self._r.keys(pattern)
        if keys:
            self._r.delete(*keys)
