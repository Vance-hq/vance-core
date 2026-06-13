"""Analytics Agent unit tests — no live HTTP, DB, or external services."""

from __future__ import annotations

import math
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from agents.analytics.ab_test_manager import ABTestManager, _proportions_z_test
from agents.analytics.cross_product_reporter import CrossProductReporter, _pct_change
from agents.analytics.db import AnalyticsDB
from agents.analytics.engagement_scorer import EngagementScorer, _assign_tier, _compute_score
from agents.analytics.feature_tracker import FeatureTracker
from agents.analytics.funnel_analyzer import FunnelAnalyzer
from agents.analytics.main import AnalyticsAgent
from agents.analytics.usage_collector import UsageCollector
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


def _make_agent(cfg: dict | None = None) -> AnalyticsAgent:
    config = MagicMock()
    config.custom = cfg or {}
    config.llm_system_prompt = ""
    config.poll_interval_seconds = 5

    agent = AnalyticsAgent.__new__(AnalyticsAgent)
    agent.agent_name = "analytics"
    agent.config = config

    db = MagicMock(spec=AnalyticsDB)
    agent._db = db
    agent._usage = MagicMock()
    agent._funnel = MagicMock()
    agent._cohort = MagicMock()
    agent._feature = MagicMock()
    agent._engagement = MagicMock()
    agent._cross = MagicMock()
    agent._ab = MagicMock()
    agent._query = MagicMock()
    return agent


# ------------------------------------------------------------------
# Dispatch — unknown action
# ------------------------------------------------------------------

def test_unknown_action_returns_failure():
    agent = _make_agent()
    result = agent.handle(_make_task("not_a_real_action"))
    assert result.success is False
    assert "Unknown analytics action" in result.output["error"]


# ------------------------------------------------------------------
# Dispatch — usage_snapshot
# ------------------------------------------------------------------

def test_usage_snapshot_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("usage_snapshot"))
    assert result.success is False


def test_usage_snapshot_calls_collector():
    agent = _make_agent()
    agent._usage.run.return_value = {"product": "starpio", "date": "2026-06-12", "metrics": {}}
    result = agent.handle(_make_task("usage_snapshot", {"product": "starpio"}))
    assert result.success is True
    agent._usage.run.assert_called_once_with(product="starpio", date_str=None)


def test_usage_snapshot_passes_date():
    agent = _make_agent()
    agent._usage.run.return_value = {"product": "starpio", "date": "2026-06-01", "metrics": {}}
    agent.handle(_make_task("usage_snapshot", {"product": "starpio", "date": "2026-06-01"}))
    agent._usage.run.assert_called_once_with(product="starpio", date_str="2026-06-01")


# ------------------------------------------------------------------
# Dispatch — funnel_analysis
# ------------------------------------------------------------------

def test_funnel_analysis_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("funnel_analysis"))
    assert result.success is False


def test_funnel_analysis_dispatches():
    agent = _make_agent()
    agent._funnel.run.return_value = {"product": "oneserv", "steps": [], "regressions": []}
    result = agent.handle(_make_task("funnel_analysis", {"product": "oneserv"}))
    assert result.success is True
    agent._funnel.run.assert_called_once_with(product="oneserv", date_str=None)


def test_funnel_analysis_with_regression_in_output():
    agent = _make_agent()
    agent._funnel.run.return_value = {
        "product": "oneserv",
        "steps": [{"step": "visit", "count": 1000}],
        "regressions": [{"step": "signup", "drop_pct": 0.20}],
    }
    result = agent.handle(_make_task("funnel_analysis", {"product": "oneserv"}))
    assert len(result.output["regressions"]) == 1


# ------------------------------------------------------------------
# Dispatch — cohort_analysis
# ------------------------------------------------------------------

def test_cohort_analysis_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("cohort_analysis"))
    assert result.success is False


def test_cohort_analysis_dispatches():
    agent = _make_agent()
    agent._cohort.run.return_value = {"product": "starpio", "cohort_month": "2026-05"}
    result = agent.handle(_make_task("cohort_analysis", {"product": "starpio", "cohort_month": "2026-05"}))
    assert result.success is True
    agent._cohort.run.assert_called_once_with(product="starpio", cohort_month="2026-05")


# ------------------------------------------------------------------
# Dispatch — feature_usage
# ------------------------------------------------------------------

def test_feature_usage_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("feature_usage"))
    assert result.success is False


def test_feature_usage_dispatches():
    agent = _make_agent()
    agent._feature.run.return_value = {"product": "starpio", "features": []}
    result = agent.handle(_make_task("feature_usage", {"product": "starpio"}))
    assert result.success is True


# ------------------------------------------------------------------
# Dispatch — engagement_score
# ------------------------------------------------------------------

def test_engagement_score_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("engagement_score"))
    assert result.success is False


def test_engagement_score_dispatches():
    agent = _make_agent()
    agent._engagement.run.return_value = {"product": "starpio", "users_scored": 42, "tier_counts": {}}
    result = agent.handle(_make_task("engagement_score", {"product": "starpio"}))
    assert result.success is True
    assert result.output["users_scored"] == 42


# ------------------------------------------------------------------
# Dispatch — cross_product_report
# ------------------------------------------------------------------

def test_cross_product_report_dispatches():
    agent = _make_agent()
    agent._cross.run.return_value = {"total_active_users": 200, "products": [], "anomalies": []}
    result = agent.handle(_make_task("cross_product_report"))
    assert result.success is True
    agent._cross.run.assert_called_once()


# ------------------------------------------------------------------
# Dispatch — ab_test_tracker
# ------------------------------------------------------------------

def test_ab_test_register():
    agent = _make_agent()
    agent._ab.register_test.return_value = {"test_id": "abc", "status": "running"}
    result = agent.handle(_make_task("ab_test_tracker", {
        "sub_action": "register",
        "agent": "content",
        "product": "starpio",
        "test_name": "hero_copy",
        "variant_a": "v_a",
        "variant_b": "v_b",
        "metric": "conversion",
    }))
    assert result.success is True
    assert result.output["status"] == "running"


def test_ab_test_check_all():
    agent = _make_agent()
    agent._ab.check_all_running.return_value = {"running_tests_evaluated": 3, "newly_concluded": 1}
    result = agent.handle(_make_task("ab_test_tracker", {"sub_action": "check_all"}))
    assert result.success is True
    assert result.output["newly_concluded"] == 1


def test_ab_test_update_requires_agent():
    agent = _make_agent()
    result = agent.handle(_make_task("ab_test_tracker", {
        "product": "starpio",
        "test_name": "hero",
    }))
    assert result.success is False


# ------------------------------------------------------------------
# Dispatch — on_demand_query
# ------------------------------------------------------------------

def test_on_demand_query_requires_question():
    agent = _make_agent()
    result = agent.handle(_make_task("on_demand_query"))
    assert result.success is False


def test_on_demand_query_dispatches():
    agent = _make_agent()
    agent._query.run.return_value = {"answer": "47 signups this week.", "row_count": 1}
    result = agent.handle(_make_task("on_demand_query", {"question": "how many signups for oneserv?"}))
    assert result.success is True
    assert "answer" in result.output


# ------------------------------------------------------------------
# health_check
# ------------------------------------------------------------------

def test_health_check_passes():
    agent = _make_agent()
    agent._db.get_recent_usage.return_value = []
    assert agent.health_check() is True


def test_health_check_fails_on_exception():
    agent = _make_agent()
    agent._db.get_recent_usage.side_effect = Exception("db down")
    assert agent.health_check() is False


# ------------------------------------------------------------------
# _proportions_z_test
# ------------------------------------------------------------------

def test_z_test_insufficient_sample_returns_none():
    result = _proportions_z_test(5, 50, 5, 50)
    assert result is None


def test_z_test_no_conversions_returns_none():
    result = _proportions_z_test(0, 500, 0, 500)
    assert result is None


def test_z_test_identical_rates_high_p_value():
    p = _proportions_z_test(100, 1000, 100, 1000)
    assert p is not None
    assert p > 0.5


def test_z_test_large_difference_low_p_value():
    # 30% vs 10% conversion — should be highly significant
    p = _proportions_z_test(300, 1000, 100, 1000)
    assert p is not None
    assert p < 0.05


def test_z_test_symmetric():
    p1 = _proportions_z_test(300, 1000, 100, 1000)
    p2 = _proportions_z_test(100, 1000, 300, 1000)
    assert p1 == p2


# ------------------------------------------------------------------
# ABTestManager
# ------------------------------------------------------------------

def test_ab_register_calls_db():
    db = MagicMock(spec=AnalyticsDB)
    db.upsert_ab_test.return_value = "test-id-123"
    mgr = ABTestManager(db, {})
    result = mgr.register_test("content", "starpio", "hero_v2", "A", "B", "clicks")
    assert result["test_id"] == "test-id-123"
    assert result["status"] == "running"


def test_ab_update_not_significant_stays_running():
    db = MagicMock(spec=AnalyticsDB)
    db.get_ab_test.return_value = {"variant_a": "A", "variant_b": "B"}
    mgr = ABTestManager(db, {})
    result = mgr.update_test("content", "starpio", "hero", 500, 500, 50, 55)
    assert result["status"] == "running"
    assert result["significant"] is False


def test_ab_update_significant_concludes_and_dispatches():
    db = MagicMock(spec=AnalyticsDB)
    db.get_ab_test.return_value = {"variant_a": "A", "variant_b": "B"}
    mgr = ABTestManager(db, {})
    # 30% vs 10% — significant
    with patch("agents.analytics.ab_test_manager.TaskQueue") as MockQ:
        result = mgr.update_test("content", "starpio", "hero", 1000, 1000, 300, 100)
    assert result["significant"] is True
    assert result["winner"] in ("A", "B")
    MockQ.return_value.push.assert_called_once()


def test_ab_test_not_found_returns_error():
    db = MagicMock(spec=AnalyticsDB)
    db.get_ab_test.return_value = None
    mgr = ABTestManager(db, {})
    result = mgr.update_test("content", "starpio", "missing_test", 500, 500, 50, 50)
    assert "error" in result


def test_ab_check_all_running():
    db = MagicMock(spec=AnalyticsDB)
    db.get_running_tests.return_value = [
        {"agent": "content", "product": "starpio", "test_name": "t1",
         "sample_size_a": 50, "sample_size_b": 50, "conversions_a": 5, "conversions_b": 5,
         "variant_a": "A", "variant_b": "B"},
    ]
    db.get_ab_test.return_value = {"variant_a": "A", "variant_b": "B"}
    mgr = ABTestManager(db, {})
    result = mgr.check_all_running()
    assert result["running_tests_evaluated"] == 1


# ------------------------------------------------------------------
# _assign_tier and _compute_score
# ------------------------------------------------------------------

def test_dormant_tier_overrides_score():
    tier = _assign_tier(score=95.0, days_inactive=15, power_threshold=80, at_risk_days=7, dormant_days=14)
    assert tier == "DORMANT"


def test_at_risk_tier():
    tier = _assign_tier(score=50.0, days_inactive=8, power_threshold=80, at_risk_days=7, dormant_days=14)
    assert tier == "AT_RISK"


def test_power_user_tier():
    tier = _assign_tier(score=90.0, days_inactive=0, power_threshold=80.0, at_risk_days=7, dormant_days=14)
    assert tier == "POWER_USER"


def test_active_tier():
    tier = _assign_tier(score=50.0, days_inactive=2, power_threshold=80.0, at_risk_days=7, dormant_days=14)
    assert tier == "ACTIVE"


def test_compute_score_fully_engaged():
    user = {
        "logins_last_7d": 7,
        "features_used": 10,
        "total_features": 10,
        "avg_session_minutes": 60,
        "days_since_last_active": 0,
    }
    score = _compute_score(user, {"login_frequency": 0.30, "feature_breadth": 0.25, "session_duration": 0.25, "recency": 0.20})
    assert score == pytest.approx(100.0, rel=0.01)


def test_compute_score_inactive_user():
    user = {
        "logins_last_7d": 0,
        "features_used": 0,
        "total_features": 10,
        "avg_session_minutes": 0,
        "days_since_last_active": 30,
    }
    score = _compute_score(user, {"login_frequency": 0.30, "feature_breadth": 0.25, "session_duration": 0.25, "recency": 0.20})
    assert score == pytest.approx(0.0, abs=0.1)


def test_engagement_scorer_dispatches_at_risk():
    db = MagicMock(spec=AnalyticsDB)
    db.get_tier_counts.return_value = {"AT_RISK": 2, "ACTIVE": 5}
    scorer = EngagementScorer(db, {"at_risk_days": 7, "dormant_days": 14})

    users = [
        {"user_id": "u1", "logins_last_7d": 0, "features_used": 1, "total_features": 5,
         "avg_session_minutes": 0, "days_since_last_active": 8},
        {"user_id": "u2", "logins_last_7d": 0, "features_used": 1, "total_features": 5,
         "avg_session_minutes": 0, "days_since_last_active": 9},
    ]

    with patch.object(scorer, "_load_user_activity", return_value=users), \
         patch("agents.analytics.engagement_scorer.TaskQueue") as MockQ:
        result = scorer.run("starpio")

    assert result["at_risk_dispatched"] == 2
    MockQ.return_value.push.assert_called()


def test_engagement_scorer_dispatches_dormant():
    db = MagicMock(spec=AnalyticsDB)
    db.get_tier_counts.return_value = {"DORMANT": 1}
    scorer = EngagementScorer(db, {"at_risk_days": 7, "dormant_days": 14})

    users = [
        {"user_id": "u3", "logins_last_7d": 0, "features_used": 0, "total_features": 5,
         "avg_session_minutes": 0, "days_since_last_active": 20},
    ]

    with patch.object(scorer, "_load_user_activity", return_value=users), \
         patch("agents.analytics.engagement_scorer.TaskQueue") as MockQ:
        result = scorer.run("starpio")

    assert result["dormant_dispatched"] == 1
    MockQ.return_value.push.assert_called()


def test_engagement_scorer_no_users():
    db = MagicMock(spec=AnalyticsDB)
    scorer = EngagementScorer(db, {})
    with patch.object(scorer, "_load_user_activity", return_value=[]):
        result = scorer.run("starpio")
    assert result["users_scored"] == 0


# ------------------------------------------------------------------
# FunnelAnalyzer
# ------------------------------------------------------------------

def test_funnel_build_steps_calculates_conversion():
    db = MagicMock(spec=AnalyticsDB)
    db.get_recent_usage.return_value = []
    db.get_funnel_week_prior.return_value = []
    analyzer = FunnelAnalyzer(db, {})

    with patch.object(analyzer, "_collect_counts", return_value={
        "visit": 1000, "signup": 100, "activated": 50, "paid": 20, "retained": 15,
    }):
        result = analyzer.run("starpio", "2026-06-12")

    signup_step = next(s for s in result["steps"] if s["step"] == "signup")
    assert signup_step["conversion_rate"] == pytest.approx(0.1, rel=0.01)


def test_funnel_regression_detected():
    db = MagicMock(spec=AnalyticsDB)
    db.get_funnel_week_prior.return_value = [
        {"step": "visit", "count": 1000},
        {"step": "signup", "count": 200},   # prior 20% conversion
        {"step": "activated", "count": 100},
        {"step": "paid", "count": 50},
        {"step": "retained", "count": 40},
    ]
    analyzer = FunnelAnalyzer(db, {})

    with patch.object(analyzer, "_collect_counts", return_value={
        "visit": 1000, "signup": 100, "activated": 50, "paid": 20, "retained": 15,
    }):
        result = analyzer.run("starpio", "2026-06-12")

    regressions = result["regressions"]
    assert any(r["step"] == "signup" for r in regressions)


def test_funnel_no_regression_when_prior_missing():
    db = MagicMock(spec=AnalyticsDB)
    db.get_funnel_week_prior.return_value = []
    analyzer = FunnelAnalyzer(db, {})

    with patch.object(analyzer, "_collect_counts", return_value={
        "visit": 100, "signup": 50, "activated": 20, "paid": 5, "retained": 3,
    }):
        result = analyzer.run("starpio", "2026-06-12")

    assert result["regressions"] == []


def test_funnel_stores_each_step_in_db():
    db = MagicMock(spec=AnalyticsDB)
    db.get_funnel_week_prior.return_value = []
    analyzer = FunnelAnalyzer(db, {})

    with patch.object(analyzer, "_collect_counts", return_value={
        "visit": 100, "signup": 50, "activated": 20, "paid": 5, "retained": 3,
    }):
        analyzer.run("starpio", "2026-06-12")

    assert db.insert_funnel_step.call_count == 5


# ------------------------------------------------------------------
# UsageCollector
# ------------------------------------------------------------------

def test_usage_collector_stores_snapshot_on_success():
    db = MagicMock(spec=AnalyticsDB)
    cfg = {"products": {"starpio": {}}, "umami": {}, "supabase": {}}
    collector = UsageCollector(db, cfg)
    result = collector.run("starpio", "2026-06-12")
    assert result["product"] == "starpio"
    assert result["date"] == "2026-06-12"
    db.upsert_usage_snapshot.assert_called_once()


def test_usage_collector_calls_umami_when_configured():
    db = MagicMock(spec=AnalyticsDB)
    cfg = {
        "products": {"starpio": {"umami_website_id": "ws-123"}},
        "umami": {"base_url": "https://umami.test", "api_key": "key"},
        "supabase": {},
    }
    collector = UsageCollector(db, cfg)
    with patch("agents.analytics.usage_collector._fetch_umami") as mock_umami:
        mock_umami.return_value = {"site_visits": 500}
        result = collector.run("starpio", "2026-06-12")
    mock_umami.assert_called_once()
    assert result["metrics"]["site_visits"] == 500


# ------------------------------------------------------------------
# CrossProductReporter
# ------------------------------------------------------------------

def test_pct_change_positive():
    assert _pct_change(120.0, 100.0) == pytest.approx(0.20, rel=0.01)


def test_pct_change_negative():
    assert _pct_change(80.0, 100.0) == pytest.approx(-0.20, rel=0.01)


def test_pct_change_zero_prior():
    assert _pct_change(100.0, 0.0) is None


def test_cross_product_report_enqueues_reporting():
    db = MagicMock(spec=AnalyticsDB)
    db.get_all_products_today.return_value = [
        {"product": "starpio", "metrics": {"site_visits": 100, "active_users": 30}},
    ]
    db.get_recent_usage.return_value = [
        {"metrics": {"site_visits": 100, "active_users": 30}},
        {"metrics": {"site_visits": 80, "active_users": 25}},
    ]
    cfg = {"products": {"starpio": {}}}
    reporter = CrossProductReporter(db, cfg)
    with patch("agents.analytics.cross_product_reporter.TaskQueue") as MockQ:
        result = reporter.run()
    MockQ.return_value.push.assert_called_once()
    assert result["total_active_users"] == 30


def test_cross_product_report_detects_anomaly():
    db = MagicMock(spec=AnalyticsDB)
    db.get_all_products_today.return_value = [
        {"product": "starpio", "metrics": {"active_users": 30}},
    ]
    db.get_recent_usage.return_value = [
        {"metrics": {"active_users": 30}},
        {"metrics": {"active_users": 10}},   # +200% change — above 20% threshold
    ]
    cfg = {"products": {"starpio": {}}}
    reporter = CrossProductReporter(db, cfg)
    with patch("agents.analytics.cross_product_reporter.TaskQueue"):
        result = reporter.run()
    assert len(result["anomalies"]) >= 1


# ------------------------------------------------------------------
# AnalyticsDB — structural tests (no live DB)
# ------------------------------------------------------------------

def test_analytics_db_upsert_usage_snapshot_calls_get_db():
    db = AnalyticsDB()
    with patch("agents.analytics.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        db.upsert_usage_snapshot("starpio", "2026-06-12", {"visits": 100})
    mock_get_db.assert_called_once()


def test_analytics_db_upsert_engagement_calls_get_db():
    db = AnalyticsDB()
    with patch("agents.analytics.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        db.upsert_engagement_score("user-1", "starpio", 75.5, "ACTIVE")
    mock_get_db.assert_called_once()
