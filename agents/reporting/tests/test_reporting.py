"""Reporting agent unit tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agents.reporting.alert_broadcaster import AlertBroadcaster
from agents.reporting.brief_compiler import BriefCompiler
from agents.reporting.db import ReportingDB
from agents.reporting.main import ReportingAgent
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


def _make_agent(cfg: dict | None = None) -> ReportingAgent:
    config = MagicMock()
    config.custom = cfg or {}
    config.llm_system_prompt = ""
    config.poll_interval_seconds = 10

    agent = ReportingAgent.__new__(ReportingAgent)
    agent.agent_name = "reporting"
    agent.config = config
    agent._db = MagicMock(spec=ReportingDB)
    agent._compiler = MagicMock(spec=BriefCompiler)
    agent._broadcaster = MagicMock(spec=AlertBroadcaster)
    return agent


# ------------------------------------------------------------------
# Dispatch
# ------------------------------------------------------------------

def test_unknown_action_returns_failure():
    agent = _make_agent()
    result = agent.handle(_make_task("bad_action"))
    assert result.success is False
    assert "Unknown reporting action" in result.output["error"]


def test_add_to_brief_stores_item():
    agent = _make_agent()
    agent._db.add_brief_item.return_value = "item-id-1"
    result = agent.handle(_make_task("add_to_brief", {
        "section": "analytics",
        "data": {"total_users": 300},
        "source": "analytics",
    }))
    assert result.success is True
    assert result.output["item_id"] == "item-id-1"
    agent._db.add_brief_item.assert_called_once_with(
        section="analytics", data={"total_users": 300}, source="analytics"
    )


def test_add_to_brief_defaults_section_to_general():
    agent = _make_agent()
    agent._db.add_brief_item.return_value = "item-id-2"
    result = agent.handle(_make_task("add_to_brief", {"data": {"key": "val"}, "source": "sales"}))
    assert result.output["section"] == "general"


def test_daily_brief_calls_compiler():
    agent = _make_agent()
    agent._compiler.compile_daily.return_value = {"period": "daily", "content": "# Brief"}
    result = agent.handle(_make_task("daily_brief"))
    assert result.success is True
    agent._compiler.compile_daily.assert_called_once_with(None)


def test_daily_brief_passes_date():
    agent = _make_agent()
    agent._compiler.compile_daily.return_value = {"period": "daily", "content": "# Brief"}
    agent.handle(_make_task("daily_brief", {"date": "2026-06-10"}))
    agent._compiler.compile_daily.assert_called_once_with("2026-06-10")


def test_weekly_digest_computes_default_range():
    agent = _make_agent()
    agent._compiler.compile_weekly.return_value = {"period": "weekly", "content": "# Weekly"}
    result = agent.handle(_make_task("weekly_digest"))
    assert result.success is True
    agent._compiler.compile_weekly.assert_called_once()
    call_kwargs = agent._compiler.compile_weekly.call_args[1]
    assert "from_date" in call_kwargs
    assert "to_date" in call_kwargs


def test_weekly_digest_accepts_explicit_range():
    agent = _make_agent()
    agent._compiler.compile_weekly.return_value = {"period": "weekly", "content": "# Weekly"}
    agent.handle(_make_task("weekly_digest", {"from_date": "2026-06-06", "to_date": "2026-06-12"}))
    agent._compiler.compile_weekly.assert_called_once_with(from_date="2026-06-06", to_date="2026-06-12")


def test_alert_broadcast_calls_broadcaster():
    agent = _make_agent()
    agent._broadcaster.broadcast.return_value = {"channels_notified": ["slack"]}
    result = agent.handle(_make_task("alert_broadcast", {
        "title": "DB disk at 90%",
        "message": "Postgres disk usage critical",
        "severity": "critical",
        "source": "security",
    }))
    assert result.success is True
    agent._broadcaster.broadcast.assert_called_once_with(
        title="DB disk at 90%",
        message="Postgres disk usage critical",
        severity="critical",
        source="security",
    )


def test_export_report_returns_items():
    agent = _make_agent()
    agent._db.get_brief_items_range.return_value = [{"section": "sales", "data": {}}]
    result = agent.handle(_make_task("export_report", {"from_date": "2026-06-01", "to_date": "2026-06-12"}))
    assert result.success is True
    assert result.output["count"] == 1


# ------------------------------------------------------------------
# health_check
# ------------------------------------------------------------------

def test_health_check_passes():
    agent = _make_agent()
    agent._db.get_brief_items.return_value = []
    assert agent.health_check() is True


def test_health_check_fails_on_db_error():
    agent = _make_agent()
    agent._db.get_brief_items.side_effect = Exception("db down")
    assert agent.health_check() is False


# ------------------------------------------------------------------
# BriefCompiler
# ------------------------------------------------------------------

def test_brief_compiler_no_items_generates_fallback():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items.return_value = []
    db.save_digest.return_value = "digest-id"
    compiler = BriefCompiler(db, {})
    result = compiler.compile_daily("2026-06-12")
    assert "No items received" in result["content"]
    db.save_digest.assert_called_once()


def test_brief_compiler_calls_llm_when_items_present():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items.return_value = [
        {"section": "analytics", "data": {"active_users": 100}, "source": "analytics"},
    ]
    db.save_digest.return_value = "digest-id"
    compiler = BriefCompiler(db, {})
    with patch("agents.reporting.brief_compiler.llm") as mock_llm:
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="# Daily Brief\n• Users up 10%")]
        mock_llm.complete.return_value = mock_resp
        result = compiler.compile_daily("2026-06-12")
    assert "Daily Brief" in result["content"]
    mock_llm.complete.assert_called_once()


def test_brief_compiler_sends_email_when_recipients_configured():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items.return_value = []
    db.save_digest.return_value = "d-id"
    cfg = {"daily_recipients": ["owner@test.com"], "resend_api_key": "key123", "from_email": "vance@test.com"}
    compiler = BriefCompiler(db, cfg)
    with patch.object(compiler, "_send_email") as mock_send:
        compiler.compile_daily("2026-06-12")
    mock_send.assert_called_once()


def test_brief_compiler_marks_digest_sent():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items.return_value = []
    db.save_digest.return_value = "d-id"
    cfg = {"daily_recipients": ["a@b.com"]}
    compiler = BriefCompiler(db, cfg)
    with patch.object(compiler, "_send_email"):
        compiler.compile_daily("2026-06-12")
    db.mark_digest_sent.assert_called_once_with(period="daily", period_date="2026-06-12")


def test_weekly_digest_uses_correct_date_range():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = []
    db.save_digest.return_value = "d-id"
    compiler = BriefCompiler(db, {})
    with patch("agents.reporting.brief_compiler.llm") as mock_llm:
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="# Weekly")]
        mock_llm.complete.return_value = mock_resp
        result = compiler.compile_weekly("2026-06-06", "2026-06-12")
    assert result["period"] == "weekly"
    db.get_brief_items_range.assert_called_once_with(from_date="2026-06-06", to_date="2026-06-12")


# ------------------------------------------------------------------
# AlertBroadcaster
# ------------------------------------------------------------------

def test_broadcaster_slack_when_webhook_configured():
    cfg = {"slack_alert_webhook": "https://hooks.slack.test/abc"}
    broadcaster = AlertBroadcaster(cfg)
    with patch.object(broadcaster, "_send_slack", return_value=True) as mock_slack:
        result = broadcaster.broadcast("DB high disk", "90% used", "critical", "security")
    assert "slack" in result["channels_notified"]
    mock_slack.assert_called_once()


def test_broadcaster_no_channels_when_not_configured():
    broadcaster = AlertBroadcaster({})
    result = broadcaster.broadcast("Title", "Message", "medium", "test")
    assert result["channels_notified"] == []


def test_broadcaster_email_when_recipients_configured():
    cfg = {"alert_email_recipients": ["alert@test.com"], "resend_api_key": "key", "from_email": "from@test.com"}
    broadcaster = AlertBroadcaster(cfg)
    with patch.object(broadcaster, "_send_email", return_value=True) as mock_email, \
         patch.object(broadcaster, "_send_slack", return_value=False):
        result = broadcaster.broadcast("High error rate", "500s spiking", "high", "qa")
    assert "email" in result["channels_notified"]


def test_broadcaster_slack_failure_doesnt_crash():
    cfg = {"slack_alert_webhook": "https://bad.webhook"}
    broadcaster = AlertBroadcaster(cfg)
    with patch.object(broadcaster, "_send_slack", return_value=False):
        result = broadcaster.broadcast("Alert", "msg", "high", "test")
    assert "slack" not in result["channels_notified"]


# ------------------------------------------------------------------
# ReportingDB structural tests
# ------------------------------------------------------------------

def test_reporting_db_add_brief_item_calls_get_db():
    db = ReportingDB()
    with patch("agents.reporting.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {"id": "test-id"}
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        db.add_brief_item("analytics", {"x": 1}, "analytics")
    mock_get_db.assert_called_once()
