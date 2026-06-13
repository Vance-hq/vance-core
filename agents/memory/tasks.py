"""Celery tasks for the memory agent — daily compaction."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.memory.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.memory.tasks.daily_compact_and_purge", ignore_result=True)
def daily_compact_and_purge() -> None:
    """Run daily — delete expired memories and compact old ones per agent context."""
    import uuid

    from agents._base import AgentConfig
    from agents.memory.main import MemoryAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("memory")
    agent = MemoryAgent("memory", config)

    purge_task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.MEMORY,
        payload={"action": "forget", "expire_only": True},
    )
    try:
        agent.handle(purge_task)
    except Exception as exc:
        logger.error("daily_memory_purge_failed", error=str(exc))

    for context_key in ["analytics", "sales", "intel", "strategy"]:
        compact_task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MEMORY,
            payload={"action": "summarize", "context_key": context_key, "keep_recent": 10},
        )
        try:
            agent.handle(compact_task)
        except Exception as exc:
            logger.error("daily_memory_compact_failed", context_key=context_key, error=str(exc))
