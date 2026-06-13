"""
Memory agent — Vance's long-term brain.

Original actions (5):
  store           — persist a key/value memory with metadata and embedding
  retrieve        — semantic search (or recency fallback) over stored memories
  summarize       — compact old memories for a context key into a summary
  forget          — delete memories by pattern, expired, topic, or product
  list_recent     — list most recent memories for a context key

New actions (4):
  capture_decision   — record significant decisions + outcomes to decision_log
  build_context_brief — synthesize a 5-sentence session brief from recent decisions
  learn_preferences  — infer Dutch's behavioral preferences → write preferences.yaml
  retrieve_context   — 'what did we do about X' via vector search on decision_log
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.llm.client import llm
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .context_brief_builder import ContextBriefBuilder
from .context_retriever import ContextRetriever
from .db import MemoryDB
from .decision_capturer import DecisionCapturer
from .embedder import embed
from .preference_learner import PreferenceLearner

logger = get_logger(__name__)

_COMPACT_SYSTEM = (
    "You are a memory compaction assistant. Given a list of older memories, "
    "produce a single concise summary that preserves the key facts. "
    "Be brief — under 200 words."
)


class MemoryAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = MemoryDB()
        self._capturer = DecisionCapturer(self._db, cfg)
        self._brief_builder = ContextBriefBuilder(self._db, cfg)
        self._pref_learner = PreferenceLearner(self._db, cfg)
        self._retriever = ContextRetriever(self._db, cfg)

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            # original 5
            "store":              lambda: self._store(p),
            "retrieve":           lambda: self._retrieve(p),
            "summarize":          lambda: self._summarize(p),
            "forget":             lambda: self._forget(p),
            "list_recent":        lambda: self._list_recent(p),
            # new 4
            "capture_decision":   lambda: self._capture_decision(p),
            "build_context_brief": lambda: self._build_context_brief(p),
            "learn_preferences":  lambda: self._learn_preferences(p),
            "retrieve_context":   lambda: self._retrieve_context(p),
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

    # ------------------------------------------------------------------
    # Original 5 actions
    # ------------------------------------------------------------------

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
        topic = p.get("topic", "")
        product = p.get("product", "")

        # New: GDPR-safe targeted deletion from decision_log
        if topic:
            deleted = self._db.delete_decisions_by_topic(topic=topic)
            return {"deleted": deleted, "mode": "topic", "topic": topic}

        if product:
            deleted = self._db.delete_decisions_by_product(product=product)
            return {"deleted": deleted, "mode": "product", "product": product}

        # Original: agent_memories maintenance
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

    # ------------------------------------------------------------------
    # New 4 actions
    # ------------------------------------------------------------------

    def _capture_decision(self, p: dict[str, Any]) -> dict[str, Any]:
        agent_name = p.get("agent", "")
        completed_action = p.get("completed_action", "")
        intent = p.get("intent", "")
        outcome = p.get("outcome", "")
        product = p.get("product", "")

        if not agent_name or not completed_action:
            return {"error": "agent and completed_action are required"}

        return self._capturer.capture(
            agent=agent_name,
            action=completed_action,
            intent=intent,
            outcome=outcome,
            product=product,
        )

    def _build_context_brief(self, p: dict[str, Any]) -> dict[str, Any]:
        days = int(p.get("days", 7))
        return self._brief_builder.build(days=days)

    def _learn_preferences(self, p: dict[str, Any]) -> dict[str, Any]:
        days = int(p.get("days", 30))
        return self._pref_learner.learn(days=days)

    def _retrieve_context(self, p: dict[str, Any]) -> dict[str, Any]:
        query = p.get("query", "")
        product = p.get("product", "")
        limit = int(p.get("limit", 5))

        if not query:
            return {"error": "query required", "results": [], "count": 0}

        return self._retriever.retrieve(query=query, product=product, limit=limit)


if __name__ == "__main__":
    config = AgentConfig.load("memory")
    MemoryAgent("memory", config).run()
