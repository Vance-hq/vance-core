"""Analytics Agent unit tests — no live HTTP, DB, or external services."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agents.analytics.alerter import AnalyticsAlerter
from agents.analytics.db import AnalyticsDB
from agents.analytics.main import AnalyticsAgent
from shared.types import Task, TaskStatus


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


def _make_agent(custom: dict | None = None) -> AnalyticsAgent:
    config = MagicMock()
    config.custom = custom or {}
    config.llm_system_prompt = ""
    config.poll_interval_seconds = 5
    agent = AnalyticsAgent.__new__(AnalyticsAgent)
    agent.agent_name = "analytics"
    agent.config = config
    agent._db = MagicMock(spec=AnalyticsDB)
    agent._alerter = MagicMock(spec=AnalyticsAlerter)
    agent._reporter = MagicMock()
    agent._report_ttl = 3600
    agent._funnel_events = ["signup", "trial_started", "payment_completed"]
    agent.ask_llm = MagicMock(return_value="• MRR up → keep scaling paid ads")
    return agent


# ------------------------------------------------------------------
# Dispatch
# ------------------------------------------------------------------

def test_unknown_action_raises():
    agent = _make_agent()
    task = _make_task("nonexistent_action_xyz")
    with pytest.raises(ValueError, match="Unknown analytics action"):
        agent.handle(task)


def test_dispatch_revenue_snapshot():
    agent = _make_agent()
    mock_metrics = {"mrr": 1500.0, "arr": 18000.0, "subscription_count": 30}
    with patch("agents.analytics.main.StripeMetrics") as MockStripe:
        MockStripe.return_value.snapshot.return_value = mock_metrics
        agent._db.bulk_insert_snapshots = MagicMock()
        result = agent.handle(_make_task("revenue_snapshot"))
    assert result.success is True
    assert result.output["mrr"] == 1500.0
    agent._db.bulk_insert_snapshots.assert_called_once()


def test_dispatch_funnel_report():
    agent = _make_agent()
    mock_funnel = [
        {"event": "signup", "unique_users": 100, "conversion_from_previous": None},
        {"event": "trial_started", "unique_users": 40, "conversion_from_previous": 0.4},
        {"event": "payment_completed", "unique_users": 10, "conversion_from_previous": 0.25},
    ]
    with patch("agents.analytics.main.PostHogMetrics") as MockPH:
        MockPH.return_value.funnel.return_value = mock_funnel
        MockPH.return_value.daily_active_users.return_value = 55.0
        MockPH.return_value.new_users.return_value = 100.0
        result = agent.handle(_make_task("funnel_report"))
    assert result.success is True
    assert result.output["funnel"][0]["event"] == "signup"
    assert result.output["dau_7d"] == 55.0


def test_dispatch_growth_dashboard_uses_cache():
    agent = _make_agent()
    cached = {"revenue": {"mrr": 999}, "summary": "Test", "cached": True}
    agent._db.get_cached_report.return_value = {"revenue": {"mrr": 999}, "summary": "Test"}
    result = agent.handle(_make_task("growth_dashboard"))
    assert result.success is True
    assert result.output.get("cached") is True


def test_dispatch_growth_dashboard_force_refresh():
    agent = _make_agent()
    agent._db.get_cached_report.return_value = None
    agent._reporter.build_growth_dashboard.return_value = {"revenue": {}, "summary": "ok"}
    with patch("agents.analytics.main.StripeMetrics") as MockStripe, \
         patch("agents.analytics.main.PostHogMetrics") as MockPH, \
         patch("agents.analytics.main.GA4Metrics") as MockGA4:
        MockStripe.return_value.snapshot.return_value = {}
        MockPH.return_value.daily_active_users.return_value = 0.0
        MockPH.return_value.session_count.return_value = 0.0
        MockPH.return_value.new_users.return_value = 0.0
        MockGA4.return_value.web_overview.return_value = {}
        result = agent.handle(_make_task("growth_dashboard", {"force_refresh": True}))
    assert result.success is True
    agent._reporter.build_growth_dashboard.assert_called_once()


def test_dispatch_cohort_analysis():
    agent = _make_agent()
    cohorts = [{"month": "2026-06", "new_subscriptions": 5, "new_mrr": 500.0}]
    with patch("agents.analytics.main.StripeMetrics") as MockStripe, \
         patch("agents.analytics.main.PostHogMetrics") as MockPH:
        MockStripe.return_value.monthly_cohorts.return_value = cohorts
        MockPH.return_value.retention_by_week.return_value = []
        result = agent.handle(_make_task("cohort_analysis"))
    assert result.output["stripe_cohorts"][0]["month"] == "2026-06"


def test_dispatch_anomaly_alert_no_anomalies():
    agent = _make_agent()
    agent._db.get_latest_snapshot.return_value = {"metric_value": 1000.0}
    agent._alerter.check_and_alert.return_value = []
    result = agent.handle(_make_task("anomaly_alert"))
    assert result.output["anomalies_detected"] == 0


def test_dispatch_anomaly_alert_with_anomaly():
    agent = _make_agent()
    agent._db.get_latest_snapshot.return_value = {"metric_value": 500.0}
    fake_anomaly = {"metric": "mrr", "current": 500.0, "baseline_7d_avg": 1000.0, "change_pct": -0.5}
    agent._alerter.check_and_alert.return_value = [fake_anomaly]
    result = agent.handle(_make_task("anomaly_alert"))
    assert result.output["anomalies_detected"] == 1
    agent._alerter.check_and_alert.assert_called_once()


def test_dispatch_product_usage_report():
    agent = _make_agent()
    agent._reporter.build_product_usage_report.return_value = {"top_features": [], "summary": "ok"}
    with patch("agents.analytics.main.PostHogMetrics") as MockPH:
        MockPH.return_value.top_features.return_value = []
        MockPH.return_value.funnel.return_value = []
        result = agent.handle(_make_task("product_usage_report"))
    assert result.success is True


# ------------------------------------------------------------------
# AnalyticsAlerter logic
# ------------------------------------------------------------------

def test_alerter_no_anomaly_under_threshold():
    db = MagicMock(spec=AnalyticsDB)
    db.get_metric_average.return_value = 1000.0
    alerter = AnalyticsAlerter(db)
    # 5% change — below default 15% threshold
    anomalies = alerter.check_and_alert({"mrr": 1050.0})
    assert anomalies == []


def test_alerter_detects_drop():
    db = MagicMock(spec=AnalyticsDB)
    db.get_metric_average.return_value = 1000.0
    alerter = AnalyticsAlerter(db)
    # 40% drop — above threshold
    with patch("agents.analytics.alerter.settings") as mock_settings:
        mock_settings.ANALYTICS_ANOMALY_THRESHOLD = 0.15
        mock_settings.ANALYTICS_SLACK_CHANNEL = ""  # no slack in tests
        anomalies = alerter.check_and_alert({"mrr": 600.0})
    assert len(anomalies) == 1
    assert anomalies[0]["change_pct"] == pytest.approx(-0.4, rel=1e-3)


def test_alerter_no_baseline_skips():
    db = MagicMock(spec=AnalyticsDB)
    db.get_metric_average.return_value = None
    alerter = AnalyticsAlerter(db)
    anomalies = alerter.check_and_alert({"mrr": 1234.0})
    assert anomalies == []


# ------------------------------------------------------------------
# AnalyticsDB — audit trail only tested structurally
# ------------------------------------------------------------------

def test_analytics_db_bulk_insert_no_rows():
    db = AnalyticsDB()
    with patch("agents.analytics.db.get_db") as mock_get_db:
        db.bulk_insert_snapshots([])
        mock_get_db.assert_not_called()


def test_health_check_passes_with_db():
    agent = _make_agent()
    with patch("agents.analytics.main.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        assert agent.health_check() is True


def test_health_check_fails_on_db_error():
    agent = _make_agent()
    with patch("agents.analytics.main.get_db", side_effect=Exception("db down")):
        assert agent.health_check() is False
