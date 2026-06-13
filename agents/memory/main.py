"""
Memory agent — persistent context store across agent runs using pgvector.

Actions:
  store           — persist a key/value memory with metadata and embedding
  retrieve        — semantic search (or recency fallback) over stored memories
  summarize       — compact old memories for a context key into a summary
  forget          — delete memories by pattern or expired ones
  list_recent     — list most recent memories for a context key
"""

from __future__ import annotations

import json
from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.llm.client import llm
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .db import MemoryDB
from .embedder import embed

logger = get_logger(__name__)

_COMPACT_SYSTEM = (
    "You are a memory compaction assistant. Given a list of older memories, "
    "produce a single concise summary that preserves the key facts. "
    "Be brief — under 200 words."
)


class MemoryAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        self._db = MemoryDB()

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "store":        lambda: self._store(p),
            "retrieve":     lambda: self._retrieve(p),
            "summarize":    lambda: self._summarize(p),
            "forget":       lambda: self._forget(p),
            "list_recent":  lambda: self._list_recent(p),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown memory action: {action}"},
            )

        logger.info("memory_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.list_recent("health_check", limit=1)
            return True
        except Exception:
            return False

    def _store(self, p: dict[str, Any]) -> dict[str, Any]:
        context_key = p.get("context_key", "general")
        content = p.get("content", "")
        metadata = p.get("metadata", {})
        expires_at = p.get("expires_at")

        if not content:
            return {"error": "content required"}

        embedding = embed(content)
        mem_id = self._db.store(
            context_key=context_key,
            content=content,
            metadata=metadata,
            embedding=embedding,
            expires_at=expires_at,
        )
        return {"memory_id": mem_id, "context_key": context_key, "has_embedding": embedding is not None}

    def _retrieve(self, p: dict[str, Any]) -> dict[str, Any]:
        context_key = p.get("context_key", "general")
        query = p.get("query", "")
        limit = int(p.get("limit", 5))

        if query:
            embedding = embed(query)
            if embedding:
                memories = self._db.search_similar(context_key=context_key, embedding=embedding, limit=limit)
                return {"context_key": context_key, "query": query, "memories": memories, "method": "semantic"}

        memories = self._db.list_recent(context_key=context_key, limit=limit)
        return {"context_key": context_key, "query": query, "memories": memories, "method": "recency"}

    def _summarize(self, p: dict[str, Any]) -> dict[str, Any]:
        context_key = p.get("context_key", "general")
        keep_recent = int(p.get("keep_recent", 5))

        old_memories = self._db.summarize_and_compact(context_key=context_key, keep_recent=keep_recent)
        if not old_memories:
            return {"context_key": context_key, "compacted": 0, "summary": ""}

        content_list = "\n".join(f"- {m['content']}" for m in old_memories)
        resp = llm.complete(
            messages=[{"role": "user", "content": f"Memories to compact:\n{content_list}"}],
            system=_COMPACT_SYSTEM,
            max_tokens=300,
        )
        summary = resp.content[0].text.strip()

        old_ids = [str(m["id"]) for m in old_memories]
        self._db.delete_by_ids(old_ids)
        self._db.store(context_key=context_key, content=summary, metadata={"type": "summary"})

        return {"context_key": context_key, "compacted": len(old_ids), "summary": summary}

    def _forget(self, p: dict[str, Any]) -> dict[str, Any]:
        context_key = p.get("context_key", "")
        pattern = p.get("pattern", "")
        expire_only = p.get("expire_only", False)

        if expire_only:
            deleted = self._db.delete_expired()
            return {"deleted": deleted, "mode": "expired"}

        if pattern and context_key:
            deleted = self._db.delete_by_pattern(context_key=context_key, pattern=pattern)
            return {"deleted": deleted, "mode": "pattern", "pattern": pattern}

        deleted = self._db.delete_expired()
        return {"deleted": deleted, "mode": "expired"}

    def _list_recent(self, p: dict[str, Any]) -> dict[str, Any]:
        context_key = p.get("context_key", "general")
        limit = int(p.get("limit", 10))
        memories = self._db.list_recent(context_key=context_key, limit=limit)
        return {"context_key": context_key, "memories": memories, "count": len(memories)}


if __name__ == "__main__":
    config = AgentConfig.load("memory")
    MemoryAgent("memory", config).run()
