"""Shared data types used across core and agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    DEAD = "dead"


class Product(str, Enum):
    STARPIO = "starpio"
    ONESERV = "oneserv"
    LOCALOUTRANK = "localoutrank"
    TRUSTED_PLUMBING = "trusted_plumbing"
    VANCE_SYSTEM = "vance_system"


class AgentCapability(str, Enum):
    MARKETING = "marketing"
    OUTREACH = "outreach"
    SALES = "sales"
    REVIEWS = "reviews"
    ADS = "ads"
    ANALYTICS = "analytics"
    DEV = "dev"
    BACKUP = "backup"
    DEPLOY = "deploy"
    SCALING = "scaling"
    FINANCE = "finance"
    SECURITY = "security"
    FORGE = "forge"
    LOCAL_RANK_GRADER = "local_rank_grader"
    INTEGRATIONS = "integrations"
    REPORTING = "reporting"
    INTEL = "intel"
    STRATEGY = "strategy"
    MEMORY = "memory"
    VIDEO = "video"
    CONTENT = "content"
    SUPPORT = "support"
    QA = "qa"
    SEO = "seo"
    VIRAL = "viral"
    RESEARCH = "research"
    ONBOARDING = "onboarding"
    LAUNCH = "launch"


@dataclass
class Task:
    id: str
    agent: AgentCapability
    payload: dict[str, Any]
    priority: int = 5
    status: TaskStatus = TaskStatus.PENDING
    product: Product | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    error: str | None = None

    @classmethod
    def from_queue_dict(cls, raw: dict[str, Any]) -> Task:
        return cls(
            id=raw["id"],
            agent=AgentCapability(raw["agent"]),
            payload=raw["payload"],
            priority=raw.get("priority", 5),
            status=TaskStatus.PROCESSING,
            created_at=datetime.fromisoformat(raw["created_at"]),
        )


@dataclass
class TaskResult:
    task_id: str
    success: bool
    output: Any = None
    error: str | None = None


@dataclass
class IntentResult:
    """Output of the voice/text intent parser."""
    raw: str
    agent: AgentCapability | None
    action: str | None
    parameters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
