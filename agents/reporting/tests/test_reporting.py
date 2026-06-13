"""Reporting agent unit tests."""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agents.reporting.alert_broadcaster import AlertBroadcaster
from agents.reporting.alert_deliverer import AlertDeliverer
from agents.reporting.brief_compiler import BriefCompiler
from agents.reporting.daily_briefer import DailyBriefer
from agents.reporting.db import ReportingDB
from agents.reporting.main import ReportingAgent
from agents.reporting.on_demand_reporter import OnDemandReporter
from agents.reporting.weekly_summarizer import WeeklySummarizer
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
    agent._daily_briefer = MagicMock(spec=DailyBriefer)
    agent._weekly_summarizer = MagicMock(spec=WeeklySummarizer)
    agent._alert_deliverer = MagicMock(spec=AlertDeliverer)
    agent._on_demand_reporter = MagicMock(spec=OnDemandReporter)
    return agent


# ------------------------------------------------------------------
# Dispatch — legacy actions (backward compat)
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


def test_daily_brief_calls_daily_briefer():
    agent = _make_agent()
    agent._daily_briefer.compile.return_value = {"report_id": "r1", "sections": 3, "content": "Brief"}
    result = agent.handle(_make_task("daily_brief"))
    assert result.success is True
    agent._daily_briefer.compile.assert_called_once_with(None)


def test_daily_brief_passes_date_to_daily_briefer():
    agent = _make_agent()
    agent._daily_briefer.compile.return_value = {"report_id": "r2", "sections": 2, "content": "Brief"}
    agent.handle(_make_task("daily_brief", {"date": "2026-06-10"}))
    agent._daily_briefer.compile.assert_called_once_with("2026-06-10")


def test_legacy_weekly_digest_computes_default_range():
    agent = _make_agent()
    agent._compiler.compile_weekly.return_value = {"period": "weekly", "content": "# Weekly"}
    result = agent.handle(_make_task("weekly_digest"))
    assert result.success is True
    agent._compiler.compile_weekly.assert_called_once()
    call_kwargs = agent._compiler.compile_weekly.call_args[1]
    assert "from_date" in call_kwargs
    assert "to_date" in call_kwargs


def test_legacy_weekly_digest_accepts_explicit_range():
    agent = _make_agent()
    agent._compiler.compile_weekly.return_value = {"period": "weekly", "content": "# Weekly"}
    agent.handle(_make_task("weekly_digest", {"from_date": "2026-06-06", "to_date": "2026-06-12"}))
    agent._compiler.compile_weekly.assert_called_once_with(from_date="2026-06-06", to_date="2026-06-12")


def test_legacy_alert_broadcast_calls_broadcaster():
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


def test_legacy_export_report_returns_items():
    agent = _make_agent()
    agent._db.get_brief_items_range.return_value = [{"section": "sales", "data": {}}]
    result = agent.handle(_make_task("export_report", {"from_date": "2026-06-01", "to_date": "2026-06-12"}))
    assert result.success is True
    assert result.output["count"] == 1


# ------------------------------------------------------------------
# Dispatch — new actions
# ------------------------------------------------------------------

def test_weekly_summary_calls_summarizer():
    agent = _make_agent()
    agent._weekly_summarizer.compile.return_value = {"period": "weekly", "content": "# Summary"}
    result = agent.handle(_make_task("weekly_summary"))
    assert result.success is True
    agent._weekly_summarizer.compile.assert_called_once()


def test_weekly_summary_passes_explicit_range():
    agent = _make_agent()
    agent._weekly_summarizer.compile.return_value = {"period": "weekly", "content": "# Summary"}
    agent.handle(_make_task("weekly_summary", {"from_date": "2026-06-06", "to_date": "2026-06-12"}))
    agent._weekly_summarizer.compile.assert_called_once_with(
        from_date="2026-06-06", to_date="2026-06-12"
    )


def test_alert_deliver_calls_deliverer():
    agent = _make_agent()
    agent._alert_deliverer.deliver.return_value = {"channels_notified": ["voice", "slack"]}
    result = agent.handle(_make_task("alert_deliver", {
        "source_agent": "security",
        "alert_type": "production_down",
        "message": "API returning 503",
        "severity": "critical",
    }))
    assert result.success is True
    agent._alert_deliverer.deliver.assert_called_once_with(
        source_agent="security",
        alert_type="production_down",
        message="API returning 503",
        severity="critical",
    )


def test_alert_deliver_defaults_severity_to_high():
    agent = _make_agent()
    agent._alert_deliverer.deliver.return_value = {"channels_notified": []}
    agent.handle(_make_task("alert_deliver", {
        "source_agent": "security",
        "alert_type": "p0_bug",
        "message": "Checkout broken",
    }))
    agent._alert_deliverer.deliver.assert_called_once_with(
        source_agent="security",
        alert_type="p0_bug",
        message="Checkout broken",
        severity="high",
    )


def test_on_demand_report_calls_reporter():
    agent = _make_agent()
    agent._on_demand_reporter.generate.return_value = {"report": "Starpio MRR is $8,400"}
    result = agent.handle(_make_task("on_demand_report", {
        "intent": "how is Starpio doing",
        "product": "starpio",
    }))
    assert result.success is True
    agent._on_demand_reporter.generate.assert_called_once_with(
        intent="how is Starpio doing",
        product="starpio",
        save=False,
    )


def test_on_demand_report_passes_save_flag():
    agent = _make_agent()
    agent._on_demand_reporter.generate.return_value = {"report": "MRR data"}
    agent.handle(_make_task("on_demand_report", {
        "intent": "what is our MRR",
        "save": True,
    }))
    agent._on_demand_reporter.generate.assert_called_once_with(
        intent="what is our MRR",
        product=None,
        save=True,
    )


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
# BriefCompiler (legacy — kept for backward compat)
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
# AlertBroadcaster (legacy — kept for backward compat)
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
# DailyBriefer
# ------------------------------------------------------------------

def test_daily_briefer_no_items_generates_fallback():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items.return_value = []
    db.save_report.return_value = "rpt-001"
    briefer = DailyBriefer(db, {})
    result = briefer.compile()
    assert result["report_id"] == "rpt-001"
    assert result["sections"] == 0


def test_daily_briefer_organizes_items_into_sections():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items.return_value = [
        {"section": "revenue", "data": {"mrr": 8400}, "source": "analytics"},
        {"section": "campaigns", "data": {"emails_sent": 500}, "source": "marketing"},
        {"section": "content", "data": {"pieces_published": 3}, "source": "content"},
    ]
    db.save_report.return_value = "rpt-002"
    briefer = DailyBriefer(db, {})
    with patch("agents.reporting.daily_briefer.llm") as mock_llm:
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Good morning Dutch. Revenue is up.")]
        mock_llm.complete.return_value = mock_resp
        result = briefer.compile("2026-06-12")
    assert result["sections"] == 3
    prompt_arg = mock_llm.complete.call_args[1]["messages"][0]["content"]
    assert "revenue" in prompt_arg.lower()
    assert "campaigns" in prompt_arg.lower()


def test_daily_briefer_llm_generates_spoken_brief():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items.return_value = [
        {"section": "revenue", "data": {"mrr": 8400}, "source": "analytics"},
    ]
    db.save_report.return_value = "rpt-003"
    briefer = DailyBriefer(db, {})
    with patch("agents.reporting.daily_briefer.llm") as mock_llm:
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Good morning Dutch.")]
        mock_llm.complete.return_value = mock_resp
        result = briefer.compile("2026-06-12")
    assert "Good morning Dutch" in result["content"]
    mock_llm.complete.assert_called_once()
    system_arg = mock_llm.complete.call_args[1]["system"]
    assert "90 second" in system_arg.lower() or "90-second" in system_arg.lower()


def test_daily_briefer_delivers_via_voice():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items.return_value = []
    db.save_report.return_value = "rpt-004"
    briefer = DailyBriefer(db, {})
    with patch("agents.reporting.daily_briefer.TaskQueue") as mock_tq:
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        briefer.compile("2026-06-12")
    mock_instance.push.assert_called_once()
    push_args = mock_instance.push.call_args[0]
    assert push_args[0] == "voice"
    assert push_args[1]["action"] == "speak"


def test_daily_briefer_saves_to_reports_table():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items.return_value = []
    db.save_report.return_value = "rpt-005"
    briefer = DailyBriefer(db, {})
    with patch("agents.reporting.daily_briefer.TaskQueue"):
        briefer.compile("2026-06-12")
    db.save_report.assert_called_once()
    call_kwargs = db.save_report.call_args[1]
    assert call_kwargs["report_type"] == "daily_brief"
    assert call_kwargs["period_date"] == "2026-06-12"


def test_daily_briefer_voice_failure_doesnt_crash():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items.return_value = []
    db.save_report.return_value = "rpt-006"
    briefer = DailyBriefer(db, {})
    with patch("agents.reporting.daily_briefer.TaskQueue") as mock_tq:
        mock_tq.return_value.push.side_effect = Exception("redis down")
        result = briefer.compile("2026-06-12")
    assert result["report_id"] == "rpt-006"


def test_daily_briefer_sends_email_when_configured():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items.return_value = []
    db.save_report.return_value = "rpt-007"
    cfg = {"daily_recipients": ["dutch@test.com"], "resend_api_key": "key", "from_email": "v@v.so"}
    briefer = DailyBriefer(db, cfg)
    with patch("agents.reporting.daily_briefer.TaskQueue"), \
         patch.object(briefer, "_send_email") as mock_send:
        briefer.compile("2026-06-12")
    mock_send.assert_called_once()


# ------------------------------------------------------------------
# WeeklySummarizer
# ------------------------------------------------------------------

def test_weekly_summarizer_calls_llm_with_items():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = [
        {"section": "revenue", "data": {"mrr": 8400}, "source": "analytics"},
    ]
    db.save_report.return_value = "rpt-010"
    summarizer = WeeklySummarizer(db, {})
    with patch("agents.reporting.weekly_summarizer.llm") as mock_llm:
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="# Weekly Summary\n\nBiggest win: MRR up 12%.")]
        mock_llm.complete.return_value = mock_resp
        result = summarizer.compile(from_date="2026-06-06", to_date="2026-06-12")
    assert result["period"] == "weekly"
    mock_llm.complete.assert_called_once()
    db.get_brief_items_range.assert_called_once_with(from_date="2026-06-06", to_date="2026-06-12")


def test_weekly_summarizer_delivers_via_voice():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = []
    db.save_report.return_value = "rpt-011"
    summarizer = WeeklySummarizer(db, {})
    with patch("agents.reporting.weekly_summarizer.llm") as mock_llm, \
         patch("agents.reporting.weekly_summarizer.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text="# Weekly")]
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        summarizer.compile(from_date="2026-06-06", to_date="2026-06-12")
    mock_instance.push.assert_called_once()
    push_args = mock_instance.push.call_args[0]
    assert push_args[0] == "voice"


def test_weekly_summarizer_saves_markdown_report(tmp_path):
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = []
    db.save_report.return_value = "rpt-012"
    cfg = {"reports_dir": str(tmp_path)}
    summarizer = WeeklySummarizer(db, cfg)
    with patch("agents.reporting.weekly_summarizer.llm") as mock_llm, \
         patch("agents.reporting.weekly_summarizer.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text="# Weekly Summary\n\nGreat week.")]
        summarizer.compile(from_date="2026-06-06", to_date="2026-06-12")
    reports = list(tmp_path.iterdir())
    assert len(reports) == 1
    assert reports[0].suffix == ".md"
    assert "weekly" in reports[0].name


def test_weekly_summarizer_saves_to_reports_table():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = []
    db.save_report.return_value = "rpt-013"
    summarizer = WeeklySummarizer(db, {})
    with patch("agents.reporting.weekly_summarizer.llm") as mock_llm, \
         patch("agents.reporting.weekly_summarizer.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text="# Weekly")]
        summarizer.compile(from_date="2026-06-06", to_date="2026-06-12")
    db.save_report.assert_called_once()
    call_kwargs = db.save_report.call_args[1]
    assert call_kwargs["report_type"] == "weekly_summary"


def test_weekly_summarizer_handles_empty_week():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = []
    db.save_report.return_value = "rpt-014"
    summarizer = WeeklySummarizer(db, {})
    with patch("agents.reporting.weekly_summarizer.llm") as mock_llm, \
         patch("agents.reporting.weekly_summarizer.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text="Quiet week.")]
        result = summarizer.compile(from_date="2026-06-06", to_date="2026-06-12")
    assert result["items_processed"] == 0


def test_weekly_summarizer_prompt_requests_win_problem_recommendation():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = [
        {"section": "revenue", "data": {"mrr": 8400}, "source": "analytics"},
    ]
    db.save_report.return_value = "rpt-015"
    summarizer = WeeklySummarizer(db, {})
    with patch("agents.reporting.weekly_summarizer.llm") as mock_llm, \
         patch("agents.reporting.weekly_summarizer.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text="# Weekly")]
        summarizer.compile(from_date="2026-06-06", to_date="2026-06-12")
    system_arg = mock_llm.complete.call_args[1]["system"]
    assert "win" in system_arg.lower()
    assert "problem" in system_arg.lower() or "issue" in system_arg.lower()
    assert "recommendation" in system_arg.lower()


# ------------------------------------------------------------------
# AlertDeliverer
# ------------------------------------------------------------------

def test_alert_deliverer_logs_to_db():
    db = MagicMock(spec=ReportingDB)
    db.log_alert.return_value = "alert-001"
    deliverer = AlertDeliverer(db, {})
    with patch("agents.reporting.alert_deliverer.TaskQueue"):
        deliverer.deliver(
            source_agent="security",
            alert_type="production_down",
            message="API 503",
            severity="critical",
        )
    db.log_alert.assert_called_once_with(
        source_agent="security",
        alert_type="production_down",
        message="API 503",
    )


def test_alert_deliverer_voice_delivery_immediate():
    db = MagicMock(spec=ReportingDB)
    db.log_alert.return_value = "alert-002"
    deliverer = AlertDeliverer(db, {})
    with patch("agents.reporting.alert_deliverer.TaskQueue") as mock_tq:
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        deliverer.deliver(
            source_agent="security",
            alert_type="production_down",
            message="API 503",
            severity="critical",
        )
    mock_instance.push.assert_called_once()
    push_args = mock_instance.push.call_args[0]
    assert push_args[0] == "voice"
    assert push_args[1]["action"] == "speak"
    assert push_args[1]["priority"] == "urgent"


def test_alert_deliverer_marks_delivered_in_db():
    db = MagicMock(spec=ReportingDB)
    db.log_alert.return_value = "alert-003"
    deliverer = AlertDeliverer(db, {})
    with patch("agents.reporting.alert_deliverer.TaskQueue"):
        deliverer.deliver("security", "mrr_drop", "MRR fell 15%", "critical")
    db.mark_alert_delivered.assert_called_once_with("alert-003")


def test_alert_deliverer_slack_when_configured():
    db = MagicMock(spec=ReportingDB)
    db.log_alert.return_value = "alert-004"
    cfg = {"slack_alert_webhook": "https://hooks.slack.test/xyz"}
    deliverer = AlertDeliverer(db, cfg)
    with patch("agents.reporting.alert_deliverer.TaskQueue"), \
         patch.object(deliverer, "_send_slack", return_value=True) as mock_slack:
        result = deliverer.deliver("security", "production_down", "DB down", "critical")
    assert "slack" in result["channels_notified"]
    mock_slack.assert_called_once()


def test_alert_deliverer_email_when_configured():
    db = MagicMock(spec=ReportingDB)
    db.log_alert.return_value = "alert-005"
    cfg = {
        "alert_email_recipients": ["dutch@test.com"],
        "resend_api_key": "key",
        "from_email": "vance@v.so",
    }
    deliverer = AlertDeliverer(db, cfg)
    with patch("agents.reporting.alert_deliverer.TaskQueue"), \
         patch.object(deliverer, "_send_email", return_value=True) as mock_email:
        result = deliverer.deliver("qa", "p0_bug", "Checkout broken", "critical")
    assert "email" in result["channels_notified"]


def test_alert_deliverer_no_channels_when_not_configured():
    db = MagicMock(spec=ReportingDB)
    db.log_alert.return_value = "alert-006"
    deliverer = AlertDeliverer(db, {})
    with patch("agents.reporting.alert_deliverer.TaskQueue"):
        result = deliverer.deliver("security", "security_incident", "Breach attempt", "high")
    assert "voice" in result["channels_notified"]
    assert "slack" not in result["channels_notified"]
    assert "email" not in result["channels_notified"]


def test_alert_deliverer_voice_failure_doesnt_crash():
    db = MagicMock(spec=ReportingDB)
    db.log_alert.return_value = "alert-007"
    deliverer = AlertDeliverer(db, {})
    with patch("agents.reporting.alert_deliverer.TaskQueue") as mock_tq:
        mock_tq.return_value.push.side_effect = Exception("redis down")
        result = deliverer.deliver("security", "production_down", "down", "critical")
    assert result["alert_id"] == "alert-007"


def test_alert_deliverer_returns_channels_notified():
    db = MagicMock(spec=ReportingDB)
    db.log_alert.return_value = "alert-008"
    cfg = {"slack_alert_webhook": "https://hooks.slack.test/x"}
    deliverer = AlertDeliverer(db, cfg)
    with patch("agents.reporting.alert_deliverer.TaskQueue"), \
         patch.object(deliverer, "_send_slack", return_value=True):
        result = deliverer.deliver("analytics", "mrr_drop", "MRR -12%", "critical")
    assert "voice" in result["channels_notified"]
    assert "slack" in result["channels_notified"]


# ------------------------------------------------------------------
# OnDemandReporter
# ------------------------------------------------------------------

def test_on_demand_reporter_llm_generates_response():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = [
        {"section": "revenue", "data": {"mrr": 8400}, "source": "analytics"},
    ]
    reporter = OnDemandReporter(db, {})
    with patch("agents.reporting.on_demand_reporter.llm") as mock_llm, \
         patch("agents.reporting.on_demand_reporter.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text="Starpio MRR is $8,400.")]
        result = reporter.generate(intent="how is Starpio doing", product="starpio")
    assert "8,400" in result["report"]
    mock_llm.complete.assert_called_once()


def test_on_demand_reporter_delivers_via_voice():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = []
    reporter = OnDemandReporter(db, {})
    with patch("agents.reporting.on_demand_reporter.llm") as mock_llm, \
         patch("agents.reporting.on_demand_reporter.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text="No data found.")]
        mock_instance = MagicMock()
        mock_tq.return_value = mock_instance
        reporter.generate(intent="what is our MRR")
    mock_instance.push.assert_called_once()
    push_args = mock_instance.push.call_args[0]
    assert push_args[0] == "voice"
    assert push_args[1]["action"] == "speak"


def test_on_demand_reporter_saves_when_requested():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = []
    db.save_report.return_value = "rpt-020"
    reporter = OnDemandReporter(db, {})
    with patch("agents.reporting.on_demand_reporter.llm") as mock_llm, \
         patch("agents.reporting.on_demand_reporter.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text="Campaign data.")]
        result = reporter.generate(intent="show campaign performance", save=True)
    db.save_report.assert_called_once()
    assert result["saved"] is True


def test_on_demand_reporter_skips_save_by_default():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = []
    reporter = OnDemandReporter(db, {})
    with patch("agents.reporting.on_demand_reporter.llm") as mock_llm, \
         patch("agents.reporting.on_demand_reporter.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text="Data.")]
        result = reporter.generate(intent="show MRR")
    db.save_report.assert_not_called()
    assert result["saved"] is False


def test_on_demand_reporter_filters_by_product():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = []
    reporter = OnDemandReporter(db, {})
    with patch("agents.reporting.on_demand_reporter.llm") as mock_llm, \
         patch("agents.reporting.on_demand_reporter.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text="Starpio data.")]
        reporter.generate(intent="how is Starpio doing", product="starpio")
    prompt_arg = mock_llm.complete.call_args[1]["messages"][0]["content"]
    assert "starpio" in prompt_arg.lower()


def test_on_demand_reporter_handles_empty_data():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = []
    reporter = OnDemandReporter(db, {})
    with patch("agents.reporting.on_demand_reporter.llm") as mock_llm, \
         patch("agents.reporting.on_demand_reporter.TaskQueue"):
        mock_llm.complete.return_value.content = [MagicMock(text="No data available for this query.")]
        result = reporter.generate(intent="show campaign performance")
    assert "report" in result


def test_on_demand_reporter_voice_failure_doesnt_crash():
    db = MagicMock(spec=ReportingDB)
    db.get_brief_items_range.return_value = []
    reporter = OnDemandReporter(db, {})
    with patch("agents.reporting.on_demand_reporter.llm") as mock_llm, \
         patch("agents.reporting.on_demand_reporter.TaskQueue") as mock_tq:
        mock_llm.complete.return_value.content = [MagicMock(text="Data.")]
        mock_tq.return_value.push.side_effect = Exception("redis down")
        result = reporter.generate(intent="show MRR")
    assert "report" in result


# ------------------------------------------------------------------
# ReportingDB — new methods structural tests
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


def test_reporting_db_save_report_calls_get_db():
    db = ReportingDB()
    with patch("agents.reporting.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {"id": "rpt-test"}
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        result = db.save_report(
            report_type="daily_brief",
            product=None,
            content_text="# Brief",
            period_date="2026-06-12",
        )
    assert result == "rpt-test"
    mock_get_db.assert_called_once()


def test_reporting_db_log_alert_calls_get_db():
    db = ReportingDB()
    with patch("agents.reporting.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {"id": "alert-test"}
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        result = db.log_alert(
            source_agent="security",
            alert_type="production_down",
            message="API 503",
        )
    assert result == "alert-test"
    mock_get_db.assert_called_once()


def test_reporting_db_mark_alert_delivered_calls_get_db():
    db = ReportingDB()
    with patch("agents.reporting.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        db.mark_alert_delivered("alert-test")
    mock_get_db.assert_called_once()
