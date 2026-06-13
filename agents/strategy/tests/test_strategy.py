"""Strategy agent unit tests."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from agents.strategy.action_recommender import ActionRecommender
from agents.strategy.db import StrategyDB
from agents.strategy.growth_analyzer import GrowthAnalyzer
from agents.strategy.main import StrategyAgent
from agents.strategy.opportunity_evaluator import OpportunityEvaluator
from agents.strategy.pivot_detector import PivotDetector
from agents.strategy.product_prioritizer import ProductPrioritizer
from agents.strategy.quarterly_planner import QuarterlyPlanner
from agents.strategy.roadmap_prioritizer import RoadmapPrioritizer
from agents.strategy.signal_synthesizer import SignalSynthesizer
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
    config.custom = cfg or {"products": ["starpio", "oneserv"], "auto_execute_threshold": 0.8}
    config.llm_system_prompt = ""
    config.poll_interval_seconds = 10

    agent = StrategyAgent.__new__(StrategyAgent)
    agent.agent_name = "strategy"
    agent.config = config
    agent._db = MagicMock(spec=StrategyDB)
    agent._growth = MagicMock(spec=GrowthAnalyzer)
    agent._roadmap = MagicMock(spec=RoadmapPrioritizer)
    agent._planner = MagicMock(spec=QuarterlyPlanner)
    agent._synthesizer = MagicMock(spec=SignalSynthesizer)
    agent._recommender = MagicMock(spec=ActionRecommender)
    agent._prioritizer = MagicMock(spec=ProductPrioritizer)
    agent._pivot_detector = MagicMock(spec=PivotDetector)
    agent._opp_evaluator = MagicMock(spec=OpportunityEvaluator)
    return agent


# ------------------------------------------------------------------
# Dispatch — legacy actions (unchanged)
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
# Dispatch — new actions
# ------------------------------------------------------------------

def test_synthesize_signals_calls_synthesizer():
    agent = _make_agent()
    agent._synthesizer.synthesize.return_value = {
        "insight_id": "ins-1",
        "insight": "MRR growing across all products.",
        "products_affected": ["starpio"],
        "confidence": 0.9,
    }
    result = agent.handle(_make_task("synthesize_signals"))
    assert result.success is True
    agent._synthesizer.synthesize.assert_called_once()


def test_synthesize_signals_passes_products_from_config():
    agent = _make_agent(cfg={"products": ["starpio", "oneserv"], "auto_execute_threshold": 0.8})
    agent._synthesizer.synthesize.return_value = {"insight_id": "ins-2", "insight": "x", "products_affected": [], "confidence": 0.7}
    agent.handle(_make_task("synthesize_signals"))
    call_args = agent._synthesizer.synthesize.call_args[1]
    assert "starpio" in call_args["products"]
    assert "oneserv" in call_args["products"]


def test_recommend_next_action_calls_recommender():
    agent = _make_agent()
    agent._recommender.recommend.return_value = {
        "recommendations": [],
        "auto_executed": 0,
        "pending_approval": 0,
    }
    result = agent.handle(_make_task("recommend_next_action"))
    assert result.success is True
    agent._recommender.recommend.assert_called_once()


def test_product_prioritization_calls_prioritizer():
    agent = _make_agent()
    agent._prioritizer.prioritize.return_value = {
        "ranked_products": [{"product": "starpio", "score": 8.5, "focus": "Scale paid acquisition"}],
    }
    result = agent.handle(_make_task("product_prioritization"))
    assert result.success is True
    agent._prioritizer.prioritize.assert_called_once()


def test_pivot_detection_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("pivot_detection"))
    assert result.success is False
    assert "product" in result.output["error"].lower()


def test_pivot_detection_calls_detector():
    agent = _make_agent()
    agent._pivot_detector.detect.return_value = {
        "product": "starpio",
        "triggered": False,
        "reason": None,
    }
    result = agent.handle(_make_task("pivot_detection", {"product": "starpio"}))
    assert result.success is True
    agent._pivot_detector.detect.assert_called_once_with(product="starpio")


def test_opportunity_evaluate_requires_opportunity():
    agent = _make_agent()
    result = agent.handle(_make_task("opportunity_evaluate"))
    assert result.success is False
    assert "opportunity" in result.output["error"].lower()


def test_opportunity_evaluate_calls_evaluator():
    agent = _make_agent()
    opp = {"title": "Integrate with HubSpot", "source": "intel", "description": "High demand"}
    agent._opp_evaluator.evaluate.return_value = {"score": 9.0, "action_taken": "research_initiated"}
    result = agent.handle(_make_task("opportunity_evaluate", {"opportunity": opp}))
    assert result.success is True
    agent._opp_evaluator.evaluate.assert_called_once_with(opportunity=opp)


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
# GrowthAnalyzer (legacy — unchanged)
# ------------------------------------------------------------------

def test_growth_analyzer_calls_llm():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = [
        {"signal_type": "competitor", "summary": "Birdeye cut prices", "recommendation": "Match offer"}
    ]
    analyzer = GrowthAnalyzer(db, {})
    with patch("agents.strategy.growth_analyzer.llm") as mock_llm:
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
# RoadmapPrioritizer (legacy — unchanged)
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
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(ranked))]
        result = prioritizer.run("starpio", ["Feature A", "Feature B"])
    assert len(result["ranked_items"]) == 1
    assert result["ranked_items"][0]["rank"] == 1


# ------------------------------------------------------------------
# QuarterlyPlanner (legacy — unchanged)
# ------------------------------------------------------------------

def test_quarterly_planner_generates_plan():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    db.upsert_plan.return_value = "plan-id-1"
    planner = QuarterlyPlanner(db, {})
    okrs = [{"objective": "Grow MRR 50%", "key_results": ["Add 20 customers", "Reduce churn to 2%"]}]
    with patch("agents.strategy.quarterly_planner.llm") as mock_llm:
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
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(review_data))]
        result = planner.review_okrs("starpio", "2026-Q2")
    assert result["off_track_count"] == 1


# ------------------------------------------------------------------
# SignalSynthesizer
# ------------------------------------------------------------------

def test_signal_synthesizer_calls_llm_with_signals():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = [
        {"signal_type": "competitor", "summary": "Birdeye cut prices", "recommendation": ""},
        {"signal_type": "market", "summary": "GMB API changes coming", "recommendation": ""},
    ]
    db.save_insight.return_value = "ins-001"
    synth = SignalSynthesizer(db, {})
    with patch("agents.strategy.signal_synthesizer.llm") as mock_llm, \
         patch("agents.strategy.signal_synthesizer.TaskQueue"):
        response = {"insight": "Pricing pressure is the dominant signal.", "products_affected": ["starpio"], "confidence": 0.85}
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(response))]
        result = synth.synthesize(products=["starpio"])
    mock_llm.complete.assert_called_once()
    assert "starpio" in mock_llm.complete.call_args[1]["messages"][0]["content"]


def test_signal_synthesizer_stores_insight_to_db():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    db.save_insight.return_value = "ins-002"
    synth = SignalSynthesizer(db, {})
    with patch("agents.strategy.signal_synthesizer.llm") as mock_llm, \
         patch("agents.strategy.signal_synthesizer.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(
            {"insight": "Quiet week.", "products_affected": [], "confidence": 0.6}
        ))]
        result = synth.synthesize(products=["starpio"])
    db.save_insight.assert_called_once()
    assert result["insight_id"] == "ins-002"


def test_signal_synthesizer_delivers_via_voice():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    db.save_insight.return_value = "ins-003"
    synth = SignalSynthesizer(db, {})
    with patch("agents.strategy.signal_synthesizer.llm") as mock_llm, \
         patch("agents.strategy.signal_synthesizer.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(
            {"insight": "MRR up.", "products_affected": ["starpio"], "confidence": 0.9}
        ))]
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        synth.synthesize(products=["starpio"])
    mock_instance.push.assert_called_once()
    push_args = mock_instance.push.call_args[0]
    assert push_args[0] == "voice"
    assert push_args[1]["action"] == "speak"


def test_signal_synthesizer_no_signals_produces_fallback():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    db.save_insight.return_value = "ins-004"
    synth = SignalSynthesizer(db, {})
    with patch("agents.strategy.signal_synthesizer.llm") as mock_llm, \
         patch("agents.strategy.signal_synthesizer.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(
            {"insight": "No signals.", "products_affected": [], "confidence": 0.5}
        ))]
        result = synth.synthesize(products=["starpio"])
    assert "insight" in result
    assert result["confidence"] <= 1.0


def test_signal_synthesizer_voice_failure_doesnt_crash():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    db.save_insight.return_value = "ins-005"
    synth = SignalSynthesizer(db, {})
    with patch("agents.strategy.signal_synthesizer.llm") as mock_llm, \
         patch("agents.strategy.signal_synthesizer.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(
            {"insight": "x", "products_affected": [], "confidence": 0.5}
        ))]
        mock_tq.return_value.push.side_effect = Exception("redis down")
        result = synth.synthesize(products=["starpio"])
    assert result["insight_id"] == "ins-005"


# ------------------------------------------------------------------
# ActionRecommender
# ------------------------------------------------------------------

_THREE_RECS = [
    {"recommendation": "Launch email win-back sequence", "rationale": "Churn spike", "agent_target": "marketing", "action": "build_sequence", "confidence": 0.9, "expected_outcome": "Recover 5 users"},
    {"recommendation": "Double LinkedIn ads budget", "rationale": "ROAS improving", "agent_target": "ads", "action": "adjust_budget", "confidence": 0.75, "expected_outcome": "10 more leads"},
    {"recommendation": "Run technical SEO audit", "rationale": "Traffic drop", "agent_target": "seo", "action": "run_audit", "confidence": 0.65, "expected_outcome": "Recover 20% traffic"},
]


def test_action_recommender_generates_three_recommendations():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    db.get_recent_insights.return_value = []
    db.save_recommendation.return_value = "rec-001"
    rec = ActionRecommender(db, {"auto_execute_threshold": 0.8})
    with patch("agents.strategy.action_recommender.llm") as mock_llm, \
         patch("agents.strategy.action_recommender.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_THREE_RECS))]
        result = rec.recommend(products=["starpio"])
    assert len(result["recommendations"]) == 3


def test_action_recommender_auto_executes_high_confidence():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    db.get_recent_insights.return_value = []
    db.save_recommendation.return_value = "rec-002"
    rec = ActionRecommender(db, {"auto_execute_threshold": 0.8})
    with patch("agents.strategy.action_recommender.llm") as mock_llm, \
         patch("agents.strategy.action_recommender.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_THREE_RECS))]
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        result = rec.recommend(products=["starpio"])
    # Only the 0.9 confidence rec should auto-execute (threshold 0.8)
    assert result["auto_executed"] == 1
    # Verify TaskQueue push was called with the right agent target
    push_calls = mock_instance.push.call_args_list
    agent_targets = [c[0][0] for c in push_calls]
    assert "marketing" in agent_targets


def test_action_recommender_delivers_low_confidence_via_voice():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    db.get_recent_insights.return_value = []
    db.save_recommendation.return_value = "rec-003"
    rec = ActionRecommender(db, {"auto_execute_threshold": 0.8})
    with patch("agents.strategy.action_recommender.llm") as mock_llm, \
         patch("agents.strategy.action_recommender.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_THREE_RECS))]
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        result = rec.recommend(products=["starpio"])
    # 2 recs below 0.8 → pending_approval
    assert result["pending_approval"] == 2
    # Voice push called for low-confidence recs
    voice_pushes = [c for c in mock_instance.push.call_args_list if c[0][0] == "voice"]
    assert len(voice_pushes) >= 1


def test_action_recommender_stores_all_recommendations_to_db():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    db.get_recent_insights.return_value = []
    db.save_recommendation.return_value = "rec-004"
    rec = ActionRecommender(db, {"auto_execute_threshold": 0.8})
    with patch("agents.strategy.action_recommender.llm") as mock_llm, \
         patch("agents.strategy.action_recommender.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_THREE_RECS))]
        rec.recommend(products=["starpio"])
    assert db.save_recommendation.call_count == 3


def test_action_recommender_marks_executed_after_auto_dispatch():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    db.get_recent_insights.return_value = []
    db.save_recommendation.return_value = "rec-005"
    rec = ActionRecommender(db, {"auto_execute_threshold": 0.8})
    with patch("agents.strategy.action_recommender.llm") as mock_llm, \
         patch("agents.strategy.action_recommender.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_THREE_RECS))]
        rec.recommend(products=["starpio"])
    # mark_recommendation_executed should be called once for the 0.9 confidence rec
    db.mark_recommendation_executed.assert_called_once_with("rec-005")


def test_action_recommender_handles_llm_invalid_json():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    db.get_recent_insights.return_value = []
    rec = ActionRecommender(db, {"auto_execute_threshold": 0.8})
    with patch("agents.strategy.action_recommender.llm") as mock_llm, \
         patch("agents.strategy.action_recommender.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text="Not JSON")]
        result = rec.recommend(products=["starpio"])
    assert result["recommendations"] == []
    assert result["auto_executed"] == 0


# ------------------------------------------------------------------
# ProductPrioritizer
# ------------------------------------------------------------------

def test_product_prioritizer_scores_all_products():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    prioritizer = ProductPrioritizer(db, {})
    ranked = [
        {"product": "starpio", "score": 8.5, "mrr_growth": "high", "momentum": "strong", "focus": "Scale paid acquisition"},
        {"product": "oneserv", "score": 6.2, "mrr_growth": "flat", "momentum": "moderate", "focus": "Improve onboarding"},
    ]
    with patch("agents.strategy.product_prioritizer.llm") as mock_llm, \
         patch("agents.strategy.product_prioritizer.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(ranked))]
        result = prioritizer.prioritize(products=["starpio", "oneserv"])
    assert len(result["ranked_products"]) == 2


def test_product_prioritizer_returns_ranked_list_highest_first():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    prioritizer = ProductPrioritizer(db, {})
    ranked = [
        {"product": "starpio", "score": 8.5, "mrr_growth": "high", "momentum": "strong", "focus": "Scale"},
        {"product": "oneserv", "score": 6.2, "mrr_growth": "flat", "momentum": "moderate", "focus": "Improve"},
    ]
    with patch("agents.strategy.product_prioritizer.llm") as mock_llm, \
         patch("agents.strategy.product_prioritizer.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(ranked))]
        result = prioritizer.prioritize(products=["starpio", "oneserv"])
    scores = [p["score"] for p in result["ranked_products"]]
    assert scores == sorted(scores, reverse=True)


def test_product_prioritizer_prompt_includes_scoring_criteria():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    prioritizer = ProductPrioritizer(db, {})
    with patch("agents.strategy.product_prioritizer.llm") as mock_llm, \
         patch("agents.strategy.product_prioritizer.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps([
            {"product": "starpio", "score": 8.0, "mrr_growth": "high", "momentum": "strong", "focus": "Scale"}
        ]))]
        prioritizer.prioritize(products=["starpio"])
    system_arg = mock_llm.complete.call_args[1]["system"]
    assert "mrr" in system_arg.lower() or "growth" in system_arg.lower()
    assert "momentum" in system_arg.lower()
    assert "effort" in system_arg.lower()


def test_product_prioritizer_delivers_via_voice():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    prioritizer = ProductPrioritizer(db, {})
    with patch("agents.strategy.product_prioritizer.llm") as mock_llm, \
         patch("agents.strategy.product_prioritizer.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps([
            {"product": "starpio", "score": 8.5, "mrr_growth": "high", "momentum": "strong", "focus": "Scale"}
        ]))]
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        prioritizer.prioritize(products=["starpio"])
    mock_instance.push.assert_called_once()
    push_args = mock_instance.push.call_args[0]
    assert push_args[0] == "voice"


def test_product_prioritizer_handles_single_product():
    db = MagicMock(spec=StrategyDB)
    db.list_signals.return_value = []
    prioritizer = ProductPrioritizer(db, {})
    with patch("agents.strategy.product_prioritizer.llm") as mock_llm, \
         patch("agents.strategy.product_prioritizer.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps([
            {"product": "starpio", "score": 7.0, "mrr_growth": "moderate", "momentum": "strong", "focus": "Retain"}
        ]))]
        result = prioritizer.prioritize(products=["starpio"])
    assert len(result["ranked_products"]) == 1


# ------------------------------------------------------------------
# PivotDetector
# ------------------------------------------------------------------

_DECLINING_TREND = [
    {"week": "2026-05-26", "mrr": 9000},
    {"week": "2026-06-02", "mrr": 8500},
    {"week": "2026-06-09", "mrr": 8000},
]

_STABLE_TREND = [
    {"week": "2026-05-26", "mrr": 8000},
    {"week": "2026-06-02", "mrr": 8200},
    {"week": "2026-06-09", "mrr": 8400},
]

_PIVOT_DIAGNOSIS = {
    "diagnosis": "Pricing too high for SMB market",
    "options": [
        {"option": "Reduce pricing 20%", "rationale": "Price elasticity signals"},
        {"option": "Add a SMB-tier plan", "rationale": "Reduce friction"},
        {"option": "Pivot to enterprise only", "rationale": "Higher ACV"},
    ],
    "recommended_option": "Add a SMB-tier plan",
}


def test_pivot_detector_no_trigger_when_mrr_growing():
    db = MagicMock(spec=StrategyDB)
    db.get_mrr_trend.return_value = _STABLE_TREND
    db.get_conversion_rate.return_value = 0.03
    detector = PivotDetector(db, {})
    with patch("agents.strategy.pivot_detector.TaskQueue"):
        result = detector.detect(product="starpio")
    assert result["triggered"] is False
    assert result["product"] == "starpio"


def test_pivot_detector_triggers_on_three_declining_weeks():
    db = MagicMock(spec=StrategyDB)
    db.get_mrr_trend.return_value = _DECLINING_TREND
    db.get_conversion_rate.return_value = 0.03
    db.save_pivot_alert.return_value = "pivot-001"
    detector = PivotDetector(db, {})
    with patch("agents.strategy.pivot_detector.llm") as mock_llm, \
         patch("agents.strategy.pivot_detector.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_PIVOT_DIAGNOSIS))]
        result = detector.detect(product="starpio")
    assert result["triggered"] is True
    assert "declining_mrr" in result["reason"]


def test_pivot_detector_triggers_on_low_conversion_rate():
    db = MagicMock(spec=StrategyDB)
    db.get_mrr_trend.return_value = _STABLE_TREND
    db.get_conversion_rate.return_value = 0.008  # below 1%
    db.save_pivot_alert.return_value = "pivot-002"
    detector = PivotDetector(db, {})
    with patch("agents.strategy.pivot_detector.llm") as mock_llm, \
         patch("agents.strategy.pivot_detector.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_PIVOT_DIAGNOSIS))]
        result = detector.detect(product="starpio")
    assert result["triggered"] is True
    assert "conversion" in result["reason"]


def test_pivot_detector_llm_generates_diagnosis_three_options():
    db = MagicMock(spec=StrategyDB)
    db.get_mrr_trend.return_value = _DECLINING_TREND
    db.get_conversion_rate.return_value = 0.03
    db.save_pivot_alert.return_value = "pivot-003"
    detector = PivotDetector(db, {})
    with patch("agents.strategy.pivot_detector.llm") as mock_llm, \
         patch("agents.strategy.pivot_detector.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_PIVOT_DIAGNOSIS))]
        result = detector.detect(product="starpio")
    assert result["diagnosis"] == "Pricing too high for SMB market"
    assert len(result["options"]) == 3
    assert result["recommended_option"] == "Add a SMB-tier plan"


def test_pivot_detector_delivers_priority_voice_alert():
    db = MagicMock(spec=StrategyDB)
    db.get_mrr_trend.return_value = _DECLINING_TREND
    db.get_conversion_rate.return_value = 0.03
    db.save_pivot_alert.return_value = "pivot-004"
    detector = PivotDetector(db, {})
    with patch("agents.strategy.pivot_detector.llm") as mock_llm, \
         patch("agents.strategy.pivot_detector.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_PIVOT_DIAGNOSIS))]
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        detector.detect(product="starpio")
    mock_instance.push.assert_called_once()
    push_args = mock_instance.push.call_args[0]
    assert push_args[0] == "voice"
    assert push_args[1]["priority"] == "urgent"


def test_pivot_detector_stores_to_pivot_alerts_table():
    db = MagicMock(spec=StrategyDB)
    db.get_mrr_trend.return_value = _DECLINING_TREND
    db.get_conversion_rate.return_value = 0.03
    db.save_pivot_alert.return_value = "pivot-005"
    detector = PivotDetector(db, {})
    with patch("agents.strategy.pivot_detector.llm") as mock_llm, \
         patch("agents.strategy.pivot_detector.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_PIVOT_DIAGNOSIS))]
        result = detector.detect(product="starpio")
    db.save_pivot_alert.assert_called_once()
    call_kwargs = db.save_pivot_alert.call_args[1]
    assert call_kwargs["product"] == "starpio"
    assert result["alert_id"] == "pivot-005"


def test_pivot_detector_not_triggered_does_not_call_llm():
    db = MagicMock(spec=StrategyDB)
    db.get_mrr_trend.return_value = _STABLE_TREND
    db.get_conversion_rate.return_value = 0.04
    detector = PivotDetector(db, {})
    with patch("agents.strategy.pivot_detector.llm") as mock_llm, \
         patch("agents.strategy.pivot_detector.TaskQueue"):
        detector.detect(product="starpio")
    mock_llm.complete.assert_not_called()


# ------------------------------------------------------------------
# OpportunityEvaluator
# ------------------------------------------------------------------

_HIGH_OPP = {"title": "Integrate with HubSpot", "source": "intel", "description": "40k HubSpot users need review management", "market_size": "large"}
_LOW_OPP = {"title": "Niche podcast sponsorship", "source": "intel", "description": "Small audience", "market_size": "small"}

_HIGH_SCORE_EVAL = {"score": 9.0, "market_size": "large", "competitive_advantage": "high", "alignment": "high", "effort": "medium", "rationale": "Strong product-market fit"}
_LOW_SCORE_EVAL = {"score": 5.0, "market_size": "small", "competitive_advantage": "low", "alignment": "low", "effort": "high", "rationale": "Poor ROI"}


def test_opportunity_evaluator_calls_llm_for_evaluation():
    db = MagicMock(spec=StrategyDB)
    evaluator = OpportunityEvaluator(db, {})
    with patch("agents.strategy.opportunity_evaluator.llm") as mock_llm, \
         patch("agents.strategy.opportunity_evaluator.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_HIGH_SCORE_EVAL))]
        evaluator.evaluate(opportunity=_HIGH_OPP)
    mock_llm.complete.assert_called_once()
    prompt_arg = mock_llm.complete.call_args[1]["messages"][0]["content"]
    assert "HubSpot" in prompt_arg


def test_opportunity_evaluator_high_score_initiates_research():
    db = MagicMock(spec=StrategyDB)
    evaluator = OpportunityEvaluator(db, {})
    with patch("agents.strategy.opportunity_evaluator.llm") as mock_llm, \
         patch("agents.strategy.opportunity_evaluator.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_HIGH_SCORE_EVAL))]
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        result = evaluator.evaluate(opportunity=_HIGH_OPP)
    # Should push to research agent
    push_calls = mock_instance.push.call_args_list
    agent_targets = [c[0][0] for c in push_calls]
    assert "research" in agent_targets
    assert result["action_taken"] == "research_initiated"


def test_opportunity_evaluator_high_score_notifies_dutch_via_voice():
    db = MagicMock(spec=StrategyDB)
    evaluator = OpportunityEvaluator(db, {})
    with patch("agents.strategy.opportunity_evaluator.llm") as mock_llm, \
         patch("agents.strategy.opportunity_evaluator.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_HIGH_SCORE_EVAL))]
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        evaluator.evaluate(opportunity=_HIGH_OPP)
    push_calls = mock_instance.push.call_args_list
    voice_pushes = [c for c in push_calls if c[0][0] == "voice"]
    assert len(voice_pushes) == 1
    assert voice_pushes[0][0][1]["action"] == "speak"


def test_opportunity_evaluator_low_score_archives_only():
    db = MagicMock(spec=StrategyDB)
    evaluator = OpportunityEvaluator(db, {})
    with patch("agents.strategy.opportunity_evaluator.llm") as mock_llm, \
         patch("agents.strategy.opportunity_evaluator.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_LOW_SCORE_EVAL))]
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        result = evaluator.evaluate(opportunity=_LOW_OPP)
    # Should NOT push to research
    push_calls = mock_instance.push.call_args_list
    agent_targets = [c[0][0] for c in push_calls]
    assert "research" not in agent_targets
    assert result["action_taken"] == "archived"


def test_opportunity_evaluator_score_threshold_is_eight():
    db = MagicMock(spec=StrategyDB)
    evaluator = OpportunityEvaluator(db, {})
    borderline_eval = {"score": 8.0, "market_size": "medium", "competitive_advantage": "medium", "alignment": "high", "effort": "low", "rationale": "Borderline"}
    with patch("agents.strategy.opportunity_evaluator.llm") as mock_llm, \
         patch("agents.strategy.opportunity_evaluator.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(borderline_eval))]
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        result = evaluator.evaluate(opportunity=_HIGH_OPP)
    # Score == 8.0 meets threshold (>= 8)
    assert result["action_taken"] == "research_initiated"


def test_opportunity_evaluator_handles_llm_invalid_json():
    db = MagicMock(spec=StrategyDB)
    evaluator = OpportunityEvaluator(db, {})
    with patch("agents.strategy.opportunity_evaluator.llm") as mock_llm, \
         patch("agents.strategy.opportunity_evaluator.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text="Not JSON")]
        result = evaluator.evaluate(opportunity=_HIGH_OPP)
    assert "score" in result
    assert result["action_taken"] == "archived"


# ------------------------------------------------------------------
# StrategyDB — new methods structural tests
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


def test_strategy_db_save_insight_calls_get_db():
    db = StrategyDB()
    with patch("agents.strategy.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {"id": "ins-id"}
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        result = db.save_insight(insight="MRR rising.", products_affected=["starpio"], confidence=0.9)
    assert result == "ins-id"
    mock_get_db.assert_called_once()


def test_strategy_db_save_recommendation_calls_get_db():
    db = StrategyDB()
    with patch("agents.strategy.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {"id": "rec-id"}
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        result = db.save_recommendation(
            recommendation="Launch campaign",
            rationale="Churn spike",
            agent_target="marketing",
            confidence=0.85,
        )
    assert result == "rec-id"
    mock_get_db.assert_called_once()


def test_strategy_db_save_pivot_alert_calls_get_db():
    db = StrategyDB()
    with patch("agents.strategy.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {"id": "pivot-id"}
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        result = db.save_pivot_alert(
            product="starpio",
            diagnosis="Pricing too high",
            options=[{"option": "Reduce pricing", "rationale": "elasticity"}],
            recommended_option="Reduce pricing",
        )
    assert result == "pivot-id"
    mock_get_db.assert_called_once()
