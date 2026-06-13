"""Memory agent unit tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agents.memory.context_brief_builder import ContextBriefBuilder
from agents.memory.context_retriever import ContextRetriever
from agents.memory.db import MemoryDB
from agents.memory.decision_capturer import DecisionCapturer
from agents.memory.main import MemoryAgent
from agents.memory.preference_learner import PreferenceLearner
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
    agent._capturer = MagicMock(spec=DecisionCapturer)
    agent._brief_builder = MagicMock(spec=ContextBriefBuilder)
    agent._pref_learner = MagicMock(spec=PreferenceLearner)
    agent._retriever = MagicMock(spec=ContextRetriever)
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


# ==================================================================
# NEW ACTIONS: capture_decision, build_context_brief,
#              learn_preferences, retrieve_context, forget (extended)
# ==================================================================

# ------------------------------------------------------------------
# capture_decision dispatch
# ------------------------------------------------------------------

def test_capture_decision_requires_agent_and_completed_action():
    agent = _make_agent()
    result = agent.handle(_make_task("capture_decision", {"intent": "send campaign"}))
    assert result.success is True
    assert "error" in result.output


def test_capture_decision_dispatches():
    agent = _make_agent()
    agent._capturer.capture.return_value = {
        "decision_id": "d-001", "agent": "outreach", "action": "send_sequence",
        "product": "starpio", "has_embedding": False,
    }
    result = agent.handle(_make_task("capture_decision", {
        "agent": "outreach",
        "completed_action": "send_sequence",
        "intent": "Warm up 50 plumber leads",
        "outcome": "47 delivered, 12% open rate",
        "product": "starpio",
    }))
    assert result.success is True
    assert result.output["decision_id"] == "d-001"
    agent._capturer.capture.assert_called_once_with(
        agent="outreach",
        action="send_sequence",
        intent="Warm up 50 plumber leads",
        outcome="47 delivered, 12% open rate",
        product="starpio",
    )


def test_capture_decision_defaults_product_to_empty():
    agent = _make_agent()
    agent._capturer.capture.return_value = {"decision_id": "d-002", "agent": "sales", "action": "close_deal", "product": "", "has_embedding": False}
    result = agent.handle(_make_task("capture_decision", {"agent": "sales", "completed_action": "close_deal"}))
    assert result.success is True
    agent._capturer.capture.assert_called_once()
    _, kwargs = agent._capturer.capture.call_args
    assert kwargs["product"] == ""


# ------------------------------------------------------------------
# build_context_brief dispatch
# ------------------------------------------------------------------

def test_build_context_brief_dispatches():
    agent = _make_agent()
    agent._brief_builder.build.return_value = {
        "brief": "Here is where everything stands...",
        "decisions_included": 12,
    }
    result = agent.handle(_make_task("build_context_brief"))
    assert result.success is True
    assert "brief" in result.output
    agent._brief_builder.build.assert_called_once_with(days=7)


def test_build_context_brief_respects_days_param():
    agent = _make_agent()
    agent._brief_builder.build.return_value = {"brief": "...", "decisions_included": 3}
    agent.handle(_make_task("build_context_brief", {"days": 14}))
    agent._brief_builder.build.assert_called_once_with(days=14)


# ------------------------------------------------------------------
# learn_preferences dispatch
# ------------------------------------------------------------------

def test_learn_preferences_dispatches():
    agent = _make_agent()
    agent._pref_learner.learn.return_value = {
        "preferences_updated": 3,
        "preferences": ["short_subject_lines", "direct_cta", "morning_sends"],
    }
    result = agent.handle(_make_task("learn_preferences"))
    assert result.success is True
    assert result.output["preferences_updated"] == 3
    agent._pref_learner.learn.assert_called_once_with(days=30)


def test_learn_preferences_respects_days_param():
    agent = _make_agent()
    agent._pref_learner.learn.return_value = {"preferences_updated": 0, "preferences": []}
    agent.handle(_make_task("learn_preferences", {"days": 60}))
    agent._pref_learner.learn.assert_called_once_with(days=60)


# ------------------------------------------------------------------
# retrieve_context dispatch
# ------------------------------------------------------------------

def test_retrieve_context_requires_query():
    agent = _make_agent()
    result = agent.handle(_make_task("retrieve_context", {"product": "starpio"}))
    assert result.success is True
    assert "error" in result.output


def test_retrieve_context_dispatches():
    agent = _make_agent()
    agent._retriever.retrieve.return_value = {
        "query": "email campaigns", "product": "starpio",
        "results": [{"agent": "outreach", "action": "send_sequence"}],
        "formatted": ["outreach.send_sequence [starpio]: Warm leads → 12% open rate"],
        "method": "recency", "count": 1,
    }
    result = agent.handle(_make_task("retrieve_context", {"query": "email campaigns", "product": "starpio"}))
    assert result.success is True
    assert result.output["count"] == 1
    agent._retriever.retrieve.assert_called_once_with(query="email campaigns", product="starpio", limit=5)


def test_retrieve_context_default_limit():
    agent = _make_agent()
    agent._retriever.retrieve.return_value = {"query": "deploy", "results": [], "count": 0, "method": "recency", "formatted": [], "product": ""}
    agent.handle(_make_task("retrieve_context", {"query": "deploy"}))
    _, kwargs = agent._retriever.retrieve.call_args
    assert kwargs["limit"] == 5


# ------------------------------------------------------------------
# forget — extended with topic/product (existing tests still pass)
# ------------------------------------------------------------------

def test_forget_by_topic_deletes_from_decision_log():
    agent = _make_agent()
    agent._db.delete_decisions_by_topic.return_value = 4
    result = agent.handle(_make_task("forget", {"topic": "birdeye"}))
    assert result.success is True
    assert result.output["deleted"] == 4
    assert result.output["mode"] == "topic"
    agent._db.delete_decisions_by_topic.assert_called_once_with(topic="birdeye")


def test_forget_by_product_deletes_all_product_decisions():
    agent = _make_agent()
    agent._db.delete_decisions_by_product.return_value = 17
    result = agent.handle(_make_task("forget", {"product": "starpio"}))
    assert result.success is True
    assert result.output["mode"] == "product"
    assert result.output["deleted"] == 17
    agent._db.delete_decisions_by_product.assert_called_once_with(product="starpio")


def test_forget_topic_takes_priority_over_expire_only():
    agent = _make_agent()
    agent._db.delete_decisions_by_topic.return_value = 2
    result = agent.handle(_make_task("forget", {"topic": "outreach", "expire_only": True}))
    assert result.output["mode"] == "topic"
    agent._db.delete_expired.assert_not_called()


# ------------------------------------------------------------------
# DecisionCapturer unit tests
# ------------------------------------------------------------------

def _make_capturer(db=None, cfg=None):
    return DecisionCapturer(db or MagicMock(spec=MemoryDB), cfg or {})


def test_capturer_saves_decision_without_embedding():
    db = MagicMock(spec=MemoryDB)
    db.save_decision.return_value = "d-100"
    capturer = _make_capturer(db)
    with patch("agents.memory.decision_capturer.embed", return_value=None):
        result = capturer.capture("analytics", "usage_snapshot", "Pull weekly stats", "Snapshot saved", "starpio")
    assert result["decision_id"] == "d-100"
    assert result["has_embedding"] is False
    db.save_decision.assert_called_once()


def test_capturer_saves_decision_with_embedding():
    db = MagicMock(spec=MemoryDB)
    db.save_decision.return_value = "d-101"
    capturer = _make_capturer(db)
    with patch("agents.memory.decision_capturer.embed", return_value=[0.1] * 1536):
        result = capturer.capture("deploy", "push_release", "Deploy v2.1", "Deployed successfully", "oneserv")
    assert result["has_embedding"] is True
    call_kwargs = db.save_decision.call_args[1]
    assert call_kwargs["embedding"] is not None


def test_capturer_includes_all_fields():
    db = MagicMock(spec=MemoryDB)
    db.save_decision.return_value = "d-102"
    capturer = _make_capturer(db)
    with patch("agents.memory.decision_capturer.embed", return_value=None):
        result = capturer.capture("sales", "close_deal", "Close 3 enterprise deals", "2 closed, 1 pending", "localoutrank")
    assert result["agent"] == "sales"
    assert result["action"] == "close_deal"
    assert result["product"] == "localoutrank"


# ------------------------------------------------------------------
# ContextBriefBuilder unit tests
# ------------------------------------------------------------------

def _make_brief_builder(db=None, cfg=None):
    return ContextBriefBuilder(db or MagicMock(spec=MemoryDB), cfg or {})


def test_brief_builder_no_decisions_returns_fallback():
    db = MagicMock(spec=MemoryDB)
    db.list_recent_decisions.return_value = []
    builder = _make_brief_builder(db)
    with patch("agents.memory.context_brief_builder.TaskQueue"):
        result = builder.build()
    assert result["decisions_included"] == 0
    assert len(result["brief"]) > 0


def test_brief_builder_synthesizes_from_decisions():
    db = MagicMock(spec=MemoryDB)
    db.list_recent_decisions.return_value = [
        {"agent": "outreach", "action": "send_sequence", "intent": "warm leads", "outcome": "12% open rate", "product": "starpio"},
        {"agent": "analytics", "action": "usage_snapshot", "intent": "weekly pull", "outcome": "180 active users", "product": "oneserv"},
    ]
    builder = _make_brief_builder(db)
    with patch("agents.memory.context_brief_builder.llm") as mock_llm, \
         patch("agents.memory.context_brief_builder.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text="Here is where everything stands. Outreach is running well. Analytics show growth. OneServ active users increased. Starpio open rates are strong.")]
        result = builder.build()
    assert result["decisions_included"] == 2
    assert "brief" in result


def test_brief_builder_delivers_to_voice():
    db = MagicMock(spec=MemoryDB)
    db.list_recent_decisions.return_value = []
    builder = _make_brief_builder(db)
    with patch("agents.memory.context_brief_builder.TaskQueue") as MockQ:
        builder.build()
    MockQ.return_value.push.assert_called_once()
    call_args = MockQ.return_value.push.call_args
    assert call_args[0][0] == "voice"


def test_brief_builder_handles_llm_failure_gracefully():
    db = MagicMock(spec=MemoryDB)
    db.list_recent_decisions.return_value = [
        {"agent": "deploy", "action": "push", "intent": "deploy v2", "outcome": "success", "product": "oneserv"},
    ]
    builder = _make_brief_builder(db)
    with patch("agents.memory.context_brief_builder.llm") as mock_llm, \
         patch("agents.memory.context_brief_builder.TaskQueue"):
        mock_llm.complete.side_effect = Exception("LLM unavailable")
        result = builder.build()
    assert result["decisions_included"] == 1
    assert "1 decisions" in result["brief"]


def test_brief_builder_respects_days_param():
    db = MagicMock(spec=MemoryDB)
    db.list_recent_decisions.return_value = []
    builder = _make_brief_builder(db)
    with patch("agents.memory.context_brief_builder.TaskQueue"):
        builder.build(days=14)
    db.list_recent_decisions.assert_called_once_with(days=14, limit=30)


# ------------------------------------------------------------------
# PreferenceLearner unit tests
# ------------------------------------------------------------------

def _make_pref_learner(db=None, cfg=None):
    return PreferenceLearner(db or MagicMock(spec=MemoryDB), cfg or {"preferences_file": "/tmp/test_prefs.yaml"})


def test_pref_learner_no_decisions_returns_zero():
    db = MagicMock(spec=MemoryDB)
    db.list_recent_decisions.return_value = []
    learner = _make_pref_learner(db)
    result = learner.learn()
    assert result["preferences_updated"] == 0
    db.upsert_preference.assert_not_called()


def test_pref_learner_parses_llm_output_and_upserts():
    db = MagicMock(spec=MemoryDB)
    db.list_recent_decisions.return_value = [
        {"agent": "outreach", "action": "send_sequence", "intent": "short subject line test", "outcome": "18% open rate", "product": "starpio"},
    ]
    db.list_preferences.return_value = []
    learner = _make_pref_learner(db)
    import json
    prefs_json = json.dumps([
        {"key": "subject_line_length", "value": "under 7 words", "confidence": 0.85, "evidence": "Short subject lines got 18% vs 9% open rate"},
    ])
    with patch("agents.memory.preference_learner.llm") as mock_llm, \
         patch.object(learner, "_write_preferences_yaml"):
        mock_llm.complete.return_value.content = [MagicMock(text=prefs_json)]
        result = learner.learn()
    assert result["preferences_updated"] == 1
    assert "subject_line_length" in result["preferences"]
    db.upsert_preference.assert_called_once_with(
        key="subject_line_length",
        value="under 7 words",
        confidence=0.85,
        source_evidence="Short subject lines got 18% vs 9% open rate",
    )


def test_pref_learner_handles_llm_parse_error():
    db = MagicMock(spec=MemoryDB)
    db.list_recent_decisions.return_value = [{"agent": "x", "action": "y", "intent": "z", "outcome": "w", "product": ""}]
    learner = _make_pref_learner(db)
    with patch("agents.memory.preference_learner.llm") as mock_llm:
        mock_llm.complete.return_value.content = [MagicMock(text="not json at all")]
        result = learner.learn()
    assert result["preferences_updated"] == 0
    assert "error" in result


def test_pref_learner_writes_yaml_file():
    db = MagicMock(spec=MemoryDB)
    db.list_preferences.return_value = [
        {"key": "cta_style", "value": "direct", "confidence": 0.9},
    ]
    learner = _make_pref_learner(db, {"preferences_file": "/tmp/vance_test_prefs_write.yaml"})
    learner._write_preferences_yaml(db.list_preferences.return_value)
    import os
    assert os.path.exists("/tmp/vance_test_prefs_write.yaml")
    import yaml as yaml_lib
    with open("/tmp/vance_test_prefs_write.yaml") as f:
        data = yaml_lib.safe_load(f)
    assert "cta_style" in data
    assert data["cta_style"]["value"] == "direct"


def test_pref_learner_skips_low_confidence_prefs():
    db = MagicMock(spec=MemoryDB)
    db.list_recent_decisions.return_value = [{"agent": "x", "action": "y", "intent": "z", "outcome": "w", "product": ""}]
    db.list_preferences.return_value = []
    learner = _make_pref_learner(db)
    import json
    # Only items with key and value are saved — missing key is skipped
    prefs_json = json.dumps([
        {"value": "no key here", "confidence": 0.9, "evidence": "something"},
        {"key": "valid_pref", "value": "yes", "confidence": 0.75, "evidence": "evidence"},
    ])
    with patch("agents.memory.preference_learner.llm") as mock_llm, \
         patch.object(learner, "_write_preferences_yaml"):
        mock_llm.complete.return_value.content = [MagicMock(text=prefs_json)]
        result = learner.learn()
    assert result["preferences_updated"] == 1
    assert "valid_pref" in result["preferences"]


# ------------------------------------------------------------------
# ContextRetriever unit tests
# ------------------------------------------------------------------

def _make_retriever(db=None, cfg=None):
    return ContextRetriever(db or MagicMock(spec=MemoryDB), cfg or {})


def test_retriever_uses_semantic_when_embedding_available():
    db = MagicMock(spec=MemoryDB)
    db.search_decisions.return_value = [
        {"agent": "deploy", "action": "push_release", "intent": "deploy v2", "outcome": "ok", "product": "oneserv"},
    ]
    retriever = _make_retriever(db)
    with patch("agents.memory.context_retriever.embed", return_value=[0.1] * 1536):
        result = retriever.retrieve("what deploys did we do", product="oneserv")
    assert result["method"] == "semantic"
    assert result["count"] == 1
    db.search_decisions.assert_called_once()


def test_retriever_falls_back_to_recency_without_embedding():
    db = MagicMock(spec=MemoryDB)
    db.list_recent_decisions.return_value = [
        {"agent": "analytics", "action": "usage_snapshot", "intent": "weekly pull", "outcome": "saved", "product": "starpio"},
    ]
    retriever = _make_retriever(db)
    with patch("agents.memory.context_retriever.embed", return_value=None):
        result = retriever.retrieve("analytics snapshots")
    assert result["method"] == "recency"
    db.list_recent_decisions.assert_called_once()


def test_retriever_formats_results_for_voice():
    db = MagicMock(spec=MemoryDB)
    db.list_recent_decisions.return_value = [
        {"agent": "sales", "action": "close_deal", "intent": "close 3 deals", "outcome": "2 closed", "product": "localoutrank"},
    ]
    retriever = _make_retriever(db)
    with patch("agents.memory.context_retriever.embed", return_value=None):
        result = retriever.retrieve("deal closes")
    assert len(result["formatted"]) == 1
    assert "sales.close_deal" in result["formatted"][0]
    assert "2 closed" in result["formatted"][0]


def test_retriever_filters_by_product():
    db = MagicMock(spec=MemoryDB)
    db.search_decisions.return_value = []
    retriever = _make_retriever(db)
    with patch("agents.memory.context_retriever.embed", return_value=[0.0] * 1536):
        retriever.retrieve("campaigns", product="starpio", limit=3)
    call_kwargs = db.search_decisions.call_args[1]
    assert call_kwargs["product"] == "starpio"
    assert call_kwargs["limit"] == 3


def test_retriever_returns_empty_list_when_no_results():
    db = MagicMock(spec=MemoryDB)
    db.list_recent_decisions.return_value = []
    retriever = _make_retriever(db)
    with patch("agents.memory.context_retriever.embed", return_value=None):
        result = retriever.retrieve("unknown topic")
    assert result["count"] == 0
    assert result["formatted"] == []


# ------------------------------------------------------------------
# MemoryDB — decision_log and preferences structural tests
# ------------------------------------------------------------------

def _mock_db_conn(fetchone_val=None, fetchall_val=None):
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = fetchone_val
    mock_cur.fetchall.return_value = fetchall_val or []
    mock_conn.cursor.return_value = mock_cur
    return mock_conn


def test_db_save_decision_returns_id():
    db = MemoryDB()
    with patch("agents.memory.db.get_db", return_value=_mock_db_conn(fetchone_val={"id": "dec-id"})):
        result = db.save_decision("outreach", "send_sequence", "warm leads", "12% open rate", "starpio")
    assert result == "dec-id"


def test_db_save_decision_with_embedding():
    db = MemoryDB()
    with patch("agents.memory.db.get_db", return_value=_mock_db_conn(fetchone_val={"id": "dec-emb-id"})):
        result = db.save_decision("deploy", "push", "deploy v2", "ok", embedding=[0.1] * 1536)
    assert result == "dec-emb-id"


def test_db_list_recent_decisions_no_product():
    db = MemoryDB()
    with patch("agents.memory.db.get_db", return_value=_mock_db_conn(fetchall_val=[{"id": "d1", "agent": "sales"}])):
        result = db.list_recent_decisions(days=7)
    assert len(result) == 1


def test_db_delete_decisions_by_topic():
    db = MemoryDB()
    mock_conn = _mock_db_conn()
    mock_conn.cursor.return_value.__enter__.return_value.rowcount = 5
    with patch("agents.memory.db.get_db", return_value=mock_conn):
        result = db.delete_decisions_by_topic("birdeye")
    assert result == 5


def test_db_delete_decisions_by_product():
    db = MemoryDB()
    mock_conn = _mock_db_conn()
    mock_conn.cursor.return_value.__enter__.return_value.rowcount = 12
    with patch("agents.memory.db.get_db", return_value=mock_conn):
        result = db.delete_decisions_by_product("starpio")
    assert result == 12


def test_db_upsert_preference():
    db = MemoryDB()
    with patch("agents.memory.db.get_db", return_value=_mock_db_conn()):
        db.upsert_preference("cta_style", "direct", confidence=0.9, source_evidence="Direct CTAs 2x conversion")


def test_db_list_preferences():
    db = MemoryDB()
    prefs = [{"key": "cta_style", "value": "direct", "confidence": 0.9, "learned_at": "2026-06-12", "source_evidence": "..."}]
    with patch("agents.memory.db.get_db", return_value=_mock_db_conn(fetchall_val=prefs)):
        result = db.list_preferences()
    assert len(result) == 1
    assert result[0]["key"] == "cta_style"
