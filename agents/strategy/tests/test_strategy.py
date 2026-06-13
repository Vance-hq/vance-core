"""Strategy agent unit tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agents.strategy.db import StrategyDB
from agents.strategy.growth_analyzer import GrowthAnalyzer
from agents.strategy.main import StrategyAgent
from agents.strategy.quarterly_planner import QuarterlyPlanner
from agents.strategy.roadmap_prioritizer import RoadmapPrioritizer
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


def _make_agent(cfg: dict | None = None) -> StrategyAgent:
    config = MagicMock()
    config.custom = cfg or {}
    config.llm_system_prompt = ""
    config.poll_interval_seconds = 10

    agent = StrategyAgent.__new__(StrategyAgent)
    agent.agent_name = "strategy"
    agent.config = config
    agent._db = MagicMock(spec=StrategyDB)
    agent._growth = MagicMock(spec=GrowthAnalyzer)
    agent._roadmap = MagicMock(spec=RoadmapPrioritizer)
    agent._planner = MagicMock(spec=QuarterlyPlanner)
    return agent


# ------------------------------------------------------------------
# Dispatch
# ------------------------------------------------------------------

def test_unknown_action_returns_failure():
    agent = _make_agent()
    result = agent.handle(_make_task("bad_action"))
    assert result.success is False
    assert "Unknown strategy action" in result.output["error"]


def test_analyze_growth_levers_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("analyze_growth_levers"))
    assert result.success is False


def test_analyze_growth_levers_dispatches():
    agent = _make_agent()
    agent._growth.run.return_value = {"product": "starpio", "levers": [], "blockers": []}
    result = agent.handle(_make_task("analyze_growth_levers", {"product": "starpio"}))
    assert result.success is True
    agent._growth.run.assert_called_once_with(product="starpio")


def test_roadmap_priority_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("roadmap_priority"))
    assert result.success is False


def test_roadmap_priority_passes_backlog():
    agent = _make_agent()
    agent._roadmap.run.return_value = {"product": "starpio", "ranked_items": []}
    result = agent.handle(_make_task("roadmap_priority", {
        "product": "starpio",
        "backlog": ["Feature A", "Feature B"],
    }))
    assert result.success is True
    agent._roadmap.run.assert_called_once_with(product="starpio", backlog=["Feature A", "Feature B"])


def test_competitor_signal_ingested():
    agent = _make_agent()
    agent._db.save_signal.return_value = "sig-id-1"
    result = agent.handle(_make_task("competitor_signal", {
        "product": "starpio",
        "competitor": "birdeye",
        "summary": "Birdeye cut pricing",
        "recommended_response": "Match with a limited offer",
        "source": "research",
    }))
    assert result.success is True
    assert result.output["signal_id"] == "sig-id-1"
    assert result.output["signal_type"] == "competitor"


def test_market_signal_ingested():
    agent = _make_agent()
    agent._db.save_signal.return_value = "sig-id-2"
    result = agent.handle(_make_task("market_signal", {
        "product": "oneserv",
        "signals": [{"headline": "Field service market growing 15% YoY"}],
        "source": "intel",
    }))
    assert result.success is True
    assert result.output["signal_type"] == "market"


def test_retention_signal_ingested():
    agent = _make_agent()
    agent._db.save_signal.return_value = "sig-id-3"
    result = agent.handle(_make_task("retention_signal", {
        "product": "starpio",
        "insights": ["Cohort May 2026 retains 20% better than April"],
        "recommendation": "Investigate May onboarding changes",
        "source": "analytics",
    }))
    assert result.success is True
    assert result.output["signal_type"] == "retention"


def test_quarterly_plan_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("quarterly_plan", {"quarter": "2026-Q3"}))
    assert result.success is False


def test_quarterly_plan_requires_quarter():
    agent = _make_agent()
    result = agent.handle(_make_task("quarterly_plan", {"product": "starpio"}))
    assert result.success is False


def test_quarterly_plan_dispatches():
    agent = _make_agent()
    agent._planner.generate_plan.return_value = {"product": "starpio", "quarter": "2026-Q3", "okrs": []}
    result = agent.handle(_make_task("quarterly_plan", {"product": "starpio", "quarter": "2026-Q3"}))
    assert result.success is True
    agent._planner.generate_plan.assert_called_once_with(product="starpio", quarter="2026-Q3")


def test_okr_review_dispatches():
    agent = _make_agent()
    agent._planner.review_okrs.return_value = {"review": [], "off_track_count": 0}
    result = agent.handle(_make_task("okr_review", {"product": "starpio", "quarter": "2026-Q2"}))
    assert result.success is True


# ------------------------------------------------------------------
# health_check
# ------------------------------------------------------------------

def test_health_check_passes():
    agent = _make_agent()
    agent._db.list_signals.return_value = []
    assert agent.health_check() is True


def test_health_check_fails_on_exception():
    agent = _make_agent()
    agent._db.list_signals.side_effect = Exception("db down")
    assert agent.health_check() is False


# ------------------------------------------------------------------
# GrowthAnalyzer
# ------------------------------------------------------------------

def test_growth_analyzer_calls_llm():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = [
        {"signal_type": "competitor", "summary": "Birdeye cut prices", "recommendation": "Match offer"}
    ]
    analyzer = GrowthAnalyzer(db, {})
    with patch("agents.strategy.growth_analyzer.llm") as mock_llm:
        import json
        data = {"levers": [{"name": "Paid ads", "impact": "high", "action": "Double budget"}],
                "blockers": [], "priority_action": "Scale ads"}
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(data))]
        result = analyzer.run("starpio")
    assert "levers" in result
    assert result["levers"][0]["name"] == "Paid ads"


def test_growth_analyzer_handles_invalid_llm_json():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    analyzer = GrowthAnalyzer(db, {})
    with patch("agents.strategy.growth_analyzer.llm") as mock_llm:
        mock_llm.complete.return_value.content = [MagicMock(text="Not JSON")]
        result = analyzer.run("starpio")
    assert "priority_action" in result


# ------------------------------------------------------------------
# RoadmapPrioritizer
# ------------------------------------------------------------------

def test_roadmap_empty_backlog_returns_no_items():
    db = MagicMock(spec=StrategyDB)
    prioritizer = RoadmapPrioritizer(db, {})
    result = prioritizer.run("starpio", [])
    assert result["ranked_items"] == []


def test_roadmap_calls_llm_with_backlog():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    prioritizer = RoadmapPrioritizer(db, {})
    ranked = [{"item": "Feature A", "rank": 1, "rationale": "High impact", "estimated_impact": "high"}]
    with patch("agents.strategy.roadmap_prioritizer.llm") as mock_llm:
        import json
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(ranked))]
        result = prioritizer.run("starpio", ["Feature A", "Feature B"])
    assert len(result["ranked_items"]) == 1
    assert result["ranked_items"][0]["rank"] == 1


# ------------------------------------------------------------------
# QuarterlyPlanner
# ------------------------------------------------------------------

def test_quarterly_planner_generates_plan():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    db.upsert_plan.return_value = "plan-id-1"
    planner = QuarterlyPlanner(db, {})
    okrs = [{"objective": "Grow MRR 50%", "key_results": ["Add 20 customers", "Reduce churn to 2%"]}]
    with patch("agents.strategy.quarterly_planner.llm") as mock_llm:
        import json
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(okrs))]
        result = planner.generate_plan("starpio", "2026-Q3")
    assert result["plan_id"] == "plan-id-1"
    assert len(result["okrs"]) == 1


def test_quarterly_planner_review_no_plan_returns_error():
    db = MagicMock(spec=StrategyDB)
    db.get_plan.return_value = None
    planner = QuarterlyPlanner(db, {})
    result = planner.review_okrs("starpio", "2026-Q1")
    assert "error" in result


def test_quarterly_planner_review_flags_off_track():
    db = MagicMock(spec=StrategyDB)
    db.get_plan.return_value = {"okrs": [{"objective": "Grow MRR 50%", "key_results": []}]}
    db.list_signals.return_value = []
    planner = QuarterlyPlanner(db, {})
    review_data = [{"objective": "Grow MRR 50%", "status": "off_track", "note": "MRR flat"}]
    with patch("agents.strategy.quarterly_planner.llm") as mock_llm:
        import json
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(review_data))]
        result = planner.review_okrs("starpio", "2026-Q2")
    assert result["off_track_count"] == 1


# ------------------------------------------------------------------
# StrategyDB structural
# ------------------------------------------------------------------

def test_strategy_db_save_signal_calls_get_db():
    db = StrategyDB()
    with patch("agents.strategy.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {"id": "sig-id"}
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        result = db.save_signal("starpio", "competitor", "Summary", "Rec", "research")
    assert result == "sig-id"
