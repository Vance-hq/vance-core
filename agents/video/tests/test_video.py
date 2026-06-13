"""Video agent unit tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agents.video.db import VideoDB
from agents.video.main import VideoAgent
from agents.video.performance_tracker import PerformanceTracker
from agents.video.script_creator import ScriptCreator
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


def _make_agent(cfg: dict | None = None) -> VideoAgent:
    config = MagicMock()
    config.custom = cfg or {}
    config.llm_system_prompt = ""
    config.poll_interval_seconds = 10

    agent = VideoAgent.__new__(VideoAgent)
    agent.agent_name = "video"
    agent.config = config
    agent._db = MagicMock(spec=VideoDB)
    agent._creator = MagicMock(spec=ScriptCreator)
    agent._perf = MagicMock(spec=PerformanceTracker)
    return agent


# ------------------------------------------------------------------
# Dispatch
# ------------------------------------------------------------------

def test_unknown_action_returns_failure():
    agent = _make_agent()
    result = agent.handle(_make_task("bad_action"))
    assert result.success is False
    assert "Unknown video action" in result.output["error"]


def test_create_script_requires_topic():
    agent = _make_agent()
    result = agent.handle(_make_task("create_script", {"product": "starpio"}))
    assert result.success is False


def test_create_script_dispatches():
    agent = _make_agent()
    agent._creator.create_script.return_value = {
        "script_id": "s-001",
        "hook": "Did you know 90% of reviews go unanswered?",
        "script": "Full script here...",
        "duration_est_s": 420,
    }
    result = agent.handle(_make_task("create_script", {
        "product": "starpio",
        "topic": "Why AI review responses matter",
        "persona": "restaurant owner",
        "tone": "persuasive",
        "format": "long",
    }))
    assert result.success is True
    assert result.output["script_id"] == "s-001"
    agent._creator.create_script.assert_called_once_with(
        product="starpio",
        topic="Why AI review responses matter",
        persona="restaurant owner",
        tone="persuasive",
        fmt="long",
    )


def test_create_shorts_requires_script():
    agent = _make_agent()
    result = agent.handle(_make_task("create_shorts"))
    assert result.success is False


def test_create_shorts_dispatches():
    agent = _make_agent()
    agent._creator.create_shorts.return_value = [
        {"title": "Clip 1", "clip_outline": "Hook + demo", "duration_s": 58},
    ]
    result = agent.handle(_make_task("create_shorts", {"script": "Full long script text here"}))
    assert result.success is True
    assert len(result.output["clips"]) == 1


def test_optimize_title_requires_topic():
    agent = _make_agent()
    result = agent.handle(_make_task("optimize_title", {"current_title": "My Video"}))
    assert result.success is False


def test_optimize_title_requires_current_title():
    agent = _make_agent()
    result = agent.handle(_make_task("optimize_title", {"topic": "Reviews"}))
    assert result.success is False


def test_optimize_title_dispatches():
    agent = _make_agent()
    agent._creator.optimize_title.return_value = [
        {"title": "How AI Replies to Reviews 10x Faster", "rationale": "Adds number and benefit"},
    ]
    result = agent.handle(_make_task("optimize_title", {
        "topic": "AI review responses",
        "current_title": "AI and Reviews",
    }))
    assert result.success is True
    assert len(result.output["alternatives"]) == 1


def test_track_performance_dispatches():
    agent = _make_agent()
    agent._perf.run.return_value = {"platform": "youtube", "videos_tracked": 2, "results": []}
    result = agent.handle(_make_task("track_performance", {
        "video_ids": ["vid1", "vid2"],
        "platform": "youtube",
    }))
    assert result.success is True
    agent._perf.run.assert_called_once_with(video_ids=["vid1", "vid2"], platform="youtube")


def test_list_scripts_dispatches():
    agent = _make_agent()
    agent._db.list_scripts.return_value = [{"topic": "Review automation", "status": "draft"}]
    result = agent.handle(_make_task("list_scripts", {"product": "starpio"}))
    assert result.success is True
    assert len(result.output["scripts"]) == 1


# ------------------------------------------------------------------
# health_check
# ------------------------------------------------------------------

def test_health_check_passes():
    agent = _make_agent()
    agent._db.list_scripts.return_value = []
    assert agent.health_check() is True


def test_health_check_fails_on_exception():
    agent = _make_agent()
    agent._db.list_scripts.side_effect = Exception("db down")
    assert agent.health_check() is False


# ------------------------------------------------------------------
# ScriptCreator
# ------------------------------------------------------------------

def test_script_creator_calls_llm_and_stores():
    db = MagicMock(spec=VideoDB)
    db.save_script.return_value = "script-id-1"
    creator = ScriptCreator(db, {})

    import json
    script_data = {
        "hook": "Did you know 80% of lost reviews cost you customers?",
        "script": "Full script...",
        "cta": "Try Starpio free for 14 days",
        "duration_est_s": 360,
        "title_options": ["Option A", "Option B"],
    }
    with patch("agents.video.script_creator.llm") as mock_llm:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(script_data))]
        result = creator.create_script("starpio", "Review automation ROI", "restaurant owner", "persuasive", "long")

    assert result["script_id"] == "script-id-1"
    assert result["hook"] == script_data["hook"]
    db.save_script.assert_called_once()


def test_script_creator_handles_invalid_json():
    db = MagicMock(spec=VideoDB)
    db.save_script.return_value = "s-id"
    creator = ScriptCreator(db, {})
    with patch("agents.video.script_creator.llm") as mock_llm:
        mock_llm.complete.return_value.content = [MagicMock(text="Not valid JSON just a script")]
        result = creator.create_script("starpio", "Topic", "persona", "tone", "long")
    assert result["script_id"] == "s-id"
    assert "Not valid JSON" in result.get("script", "")


def test_create_shorts_returns_clips():
    db = MagicMock(spec=VideoDB)
    creator = ScriptCreator(db, {})
    clips = [{"title": "Clip 1", "clip_outline": "Hook", "duration_s": 45}]
    import json
    with patch("agents.video.script_creator.llm") as mock_llm:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(clips))]
        result = creator.create_shorts("Long script content here...")
    assert len(result) == 1
    assert result[0]["duration_s"] == 45


def test_optimize_title_returns_alternatives():
    db = MagicMock(spec=VideoDB)
    creator = ScriptCreator(db, {})
    alts = [{"title": "Better Title", "rationale": "More specific"}]
    import json
    with patch("agents.video.script_creator.llm") as mock_llm:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(alts))]
        result = creator.optimize_title("AI reviews", "My Review Video")
    assert result[0]["title"] == "Better Title"


# ------------------------------------------------------------------
# PerformanceTracker
# ------------------------------------------------------------------

def test_performance_tracker_empty_ids_returns_zero():
    db = MagicMock(spec=VideoDB)
    tracker = PerformanceTracker(db, {})
    result = tracker.run([])
    assert result["videos_tracked"] == 0


def test_performance_tracker_stores_and_notifies():
    db = MagicMock(spec=VideoDB)
    tracker = PerformanceTracker(db, {"youtube_api_key": "key"})
    with patch("agents.video.performance_tracker._fetch_youtube_stats") as mock_fetch, \
         patch("agents.video.performance_tracker.TaskQueue") as MockQ:
        mock_fetch.return_value = {"views": 1200, "ctr": 0.05, "avg_view_pct": 55.0}
        result = tracker.run(["vid-abc"], "youtube")
    assert result["videos_tracked"] == 1
    db.upsert_performance.assert_called_once()
    MockQ.return_value.push.assert_called_once()


def test_performance_tracker_flags_low_ctr():
    db = MagicMock(spec=VideoDB)
    tracker = PerformanceTracker(db, {})
    with patch("agents.video.performance_tracker._fetch_youtube_stats") as mock_fetch, \
         patch("agents.video.performance_tracker.TaskQueue"):
        mock_fetch.return_value = {"views": 500, "ctr": 0.01, "avg_view_pct": 60.0}
        result = tracker.run(["vid-low-ctr"])
    insights = result["results"][0]["insights"]
    assert any("low_ctr" in i for i in insights)


def test_performance_tracker_flags_low_retention():
    db = MagicMock(spec=VideoDB)
    tracker = PerformanceTracker(db, {})
    with patch("agents.video.performance_tracker._fetch_youtube_stats") as mock_fetch, \
         patch("agents.video.performance_tracker.TaskQueue"):
        mock_fetch.return_value = {"views": 500, "ctr": 0.05, "avg_view_pct": 20.0}
        result = tracker.run(["vid-low-ret"])
    insights = result["results"][0]["insights"]
    assert any("low_retention" in i for i in insights)


# ------------------------------------------------------------------
# VideoDB structural
# ------------------------------------------------------------------

def test_video_db_save_script_calls_get_db():
    db = VideoDB()
    with patch("agents.video.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {"id": "s-id"}
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        result = db.save_script("starpio", "Topic", "persona", "Script text", "Hook", 300)
    assert result == "s-id"
