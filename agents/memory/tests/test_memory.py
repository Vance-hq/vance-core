"""Memory agent unit tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agents.memory.db import MemoryDB
from agents.memory.main import MemoryAgent
from shared.types import Task


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_task(action: str, payload: dict | None = None) -> Task:
    return Task(
        id="t-001",
        agent=MagicMock(),
        payload={"action": action, **(payload or {})},
        created_at=datetime.utcnow(),
    )


def _make_agent() -> MemoryAgent:
    config = MagicMock()
    config.custom = {}
    config.llm_system_prompt = ""
    config.poll_interval_seconds = 10

    agent = MemoryAgent.__new__(MemoryAgent)
    agent.agent_name = "memory"
    agent.config = config
    agent._db = MagicMock(spec=MemoryDB)
    return agent


# ------------------------------------------------------------------
# Dispatch
# ------------------------------------------------------------------

def test_unknown_action_returns_failure():
    agent = _make_agent()
    result = agent.handle(_make_task("bad_action"))
    assert result.success is False
    assert "Unknown memory action" in result.output["error"]


# ------------------------------------------------------------------
# store
# ------------------------------------------------------------------

def test_store_requires_content():
    agent = _make_agent()
    result = agent.handle(_make_task("store", {"context_key": "sales"}))
    assert result.success is True
    assert "error" in result.output


def test_store_saves_memory():
    agent = _make_agent()
    agent._db.store.return_value = "mem-id-1"
    with patch("agents.memory.main.embed", return_value=None):
        result = agent.handle(_make_task("store", {
            "context_key": "sales",
            "content": "Churned user John upgraded after discount",
            "metadata": {"user_id": "u123"},
        }))
    assert result.success is True
    assert result.output["memory_id"] == "mem-id-1"
    agent._db.store.assert_called_once()


def test_store_includes_embedding_flag():
    agent = _make_agent()
    agent._db.store.return_value = "mem-id-2"
    with patch("agents.memory.main.embed", return_value=[0.1] * 1536):
        result = agent.handle(_make_task("store", {"context_key": "intel", "content": "Competitor raised price"}))
    assert result.output["has_embedding"] is True


def test_store_with_expires_at():
    agent = _make_agent()
    agent._db.store.return_value = "mem-id-3"
    with patch("agents.memory.main.embed", return_value=None):
        agent.handle(_make_task("store", {
            "context_key": "intel",
            "content": "Temporary note",
            "expires_at": "2026-07-01T00:00:00Z",
        }))
    call_kwargs = agent._db.store.call_args[1]
    assert call_kwargs["expires_at"] == "2026-07-01T00:00:00Z"


# ------------------------------------------------------------------
# retrieve
# ------------------------------------------------------------------

def test_retrieve_falls_back_to_recency_when_no_embedding():
    agent = _make_agent()
    agent._db.list_recent.return_value = [{"content": "Memory 1"}, {"content": "Memory 2"}]
    with patch("agents.memory.main.embed", return_value=None):
        result = agent.handle(_make_task("retrieve", {"context_key": "sales", "query": "discount"}))
    assert result.success is True
    assert result.output["method"] == "recency"
    assert len(result.output["memories"]) == 2


def test_retrieve_uses_semantic_when_embedding_available():
    agent = _make_agent()
    agent._db.search_similar.return_value = [{"content": "Relevant memory", "similarity": 0.92}]
    with patch("agents.memory.main.embed", return_value=[0.1] * 1536):
        result = agent.handle(_make_task("retrieve", {"context_key": "sales", "query": "churn recovery"}))
    assert result.output["method"] == "semantic"
    agent._db.search_similar.assert_called_once()


def test_retrieve_without_query_uses_recency():
    agent = _make_agent()
    agent._db.list_recent.return_value = []
    result = agent.handle(_make_task("retrieve", {"context_key": "analytics"}))
    assert result.output["method"] == "recency"


def test_retrieve_respects_limit():
    agent = _make_agent()
    agent._db.list_recent.return_value = []
    with patch("agents.memory.main.embed", return_value=None):
        agent.handle(_make_task("retrieve", {"context_key": "sales", "limit": 3}))
    agent._db.list_recent.assert_called_once_with(context_key="sales", limit=3)


# ------------------------------------------------------------------
# summarize
# ------------------------------------------------------------------

def test_summarize_compacts_old_memories():
    agent = _make_agent()
    agent._db.summarize_and_compact.return_value = [
        {"id": "m1", "content": "Fact A"},
        {"id": "m2", "content": "Fact B"},
    ]
    agent._db.store.return_value = "summary-id"
    with patch("agents.memory.main.llm") as mock_llm:
        mock_llm.complete.return_value.content = [MagicMock(text="Summary: A and B happened.")]
        result = agent.handle(_make_task("summarize", {"context_key": "intel", "keep_recent": 5}))
    assert result.success is True
    assert result.output["compacted"] == 2
    agent._db.delete_by_ids.assert_called_once_with(["m1", "m2"])
    agent._db.store.assert_called_once()


def test_summarize_returns_empty_when_no_old_memories():
    agent = _make_agent()
    agent._db.summarize_and_compact.return_value = []
    result = agent.handle(_make_task("summarize", {"context_key": "intel"}))
    assert result.success is True
    assert result.output["compacted"] == 0


# ------------------------------------------------------------------
# forget
# ------------------------------------------------------------------

def test_forget_expire_only_mode():
    agent = _make_agent()
    agent._db.delete_expired.return_value = 7
    result = agent.handle(_make_task("forget", {"expire_only": True}))
    assert result.success is True
    assert result.output["deleted"] == 7
    assert result.output["mode"] == "expired"


def test_forget_by_pattern():
    agent = _make_agent()
    agent._db.delete_by_pattern.return_value = 3
    result = agent.handle(_make_task("forget", {"context_key": "intel", "pattern": "birdeye"}))
    assert result.success is True
    assert result.output["deleted"] == 3
    assert result.output["mode"] == "pattern"


def test_forget_defaults_to_expired():
    agent = _make_agent()
    agent._db.delete_expired.return_value = 0
    result = agent.handle(_make_task("forget"))
    assert result.success is True
    assert result.output["mode"] == "expired"


# ------------------------------------------------------------------
# list_recent
# ------------------------------------------------------------------

def test_list_recent_returns_memories():
    agent = _make_agent()
    agent._db.list_recent.return_value = [{"content": "m1"}, {"content": "m2"}]
    result = agent.handle(_make_task("list_recent", {"context_key": "analytics"}))
    assert result.success is True
    assert result.output["count"] == 2


def test_list_recent_default_context_key():
    agent = _make_agent()
    agent._db.list_recent.return_value = []
    agent.handle(_make_task("list_recent"))
    agent._db.list_recent.assert_called_once_with(context_key="general", limit=10)


# ------------------------------------------------------------------
# health_check
# ------------------------------------------------------------------

def test_health_check_passes():
    agent = _make_agent()
    agent._db.list_recent.return_value = []
    assert agent.health_check() is True


def test_health_check_fails_on_exception():
    agent = _make_agent()
    agent._db.list_recent.side_effect = Exception("db down")
    assert agent.health_check() is False


# ------------------------------------------------------------------
# MemoryDB structural
# ------------------------------------------------------------------

def test_memory_db_store_without_embedding():
    db = MemoryDB()
    with patch("agents.memory.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {"id": "mem-id"}
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        result = db.store("sales", "Some memory content")
    assert result == "mem-id"


def test_memory_db_delete_by_ids_skips_empty():
    db = MemoryDB()
    with patch("agents.memory.db.get_db") as mock_get_db:
        db.delete_by_ids([])
        mock_get_db.assert_not_called()
