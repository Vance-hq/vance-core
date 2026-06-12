"""Agent event types published to the Redis dashboard channel."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


EVENTS_CHANNEL = "vance:events"


class AgentEvent(str, Enum):
    TASK_STARTED = "task_started"
    TASK_COMPLETE = "task_complete"
    TASK_FAILED = "task_failed"
    STATUS_UPDATE = "status_update"
    ALERT = "alert"


class EventPayload(BaseModel):
    event_type: AgentEvent
    agent: str
    task_id: str | None = None
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
