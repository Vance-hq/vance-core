"""Forge agent unit tests — no external services required."""

from __future__ import annotations

import threading
import uuid
from unittest.mock import MagicMock, patch

import pytest

from agents.forge.monitor import SequenceMonitor
from agents.forge.optimizer import SequenceOptimizer
from agents.forge.reporter import ForgeReporter
from agents.forge.scorer import LeadScorer
from agents.forge.scraper import LeadScraper, _domain_from_website, _guess_domain
from agents.forge.sequence import SequenceLauncher
from agents.forge.warmer import DomainWarmer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_crm():
    return MagicMock()


# ---------------------------------------------------------------------------
# Scraper helpers
# ---------------------------------------------------------------------------

def test_domain_from_website_strips_prefix():
    assert _domain_from_website("https://www.acme.com/about") == "acme.com"


def test_domain_from_website_handles_empty():
    assert _domain_from_website("") == ""


def test_guess_domain_slugifies():
    assert _guess_domain("Acme HVAC & Plumbing") == "acmehvacplumbing.com"


def test_guess_domain_empty():
    assert _guess_domain("") == ""


# ---------------------------------------------------------------------------
# SequenceMonitor — reply classification (keyword fast-path)
# ---------------------------------------------------------------------------

def test_classify_reply_unsubscribe_keyword(mock_db):
    monitor = SequenceMonitor(mock_db)
    assert monitor.classify_reply("Please remove me from your list.") == "UNSUBSCRIBE"


def test_classify_reply_oof_keyword(mock_db):
    monitor = SequenceMonitor(mock_db)
    assert monitor.classify_reply("I am out of office until Monday.") == "OUT_OF_OFFICE"


def test_classify_reply_bounce_keyword(mock_db):
    monitor = SequenceMonitor(mock_db)
    assert monitor.classify_reply("Mailer-Daemon: delivery failed, user unknown.") == "BOUNCE"


@patch("agents.forge.monitor.llm")
def test_classify_reply_llm_interested(mock_llm, mock_db):
    mock_llm.complete.return_value.content = [MagicMock(text="INTERESTED")]
    monitor = SequenceMonitor(mock_db)
    result = monitor.classify_reply("Hey, I'd love to learn more about this.")
    assert result == "INTERESTED"


@patch("agents.forge.monitor.llm")
def test_classify_reply_llm_unknown_falls_back(mock_llm, mock_db):
    mock_llm.complete.return_value.content = [MagicMock(text="GARBAGE")]
    monitor = SequenceMonitor(mock_db)
    result = monitor.classify_reply("Something weird.")
    assert result == "QUESTION"


# ---------------------------------------------------------------------------
# SequenceMonitor — high bounce rate pauses sequence
# ---------------------------------------------------------------------------

def test_monitor_pauses_on_high_bounce(mock_db):
    mock_db.get_sequence_metrics.return_value = {
        "sends": 100,
        "opens": 10,
        "interested": 1,
        "unsubscribes": 0,
        "bounces": 10,
        "open_rate": 0.10,
        "reply_rate": 0.01,
        "bounce_rate": 0.10,  # > 0.08 threshold
    }
    monitor = SequenceMonitor(mock_db, bounce_alert_threshold=0.08)
    monitor.monitor("seq-123")
    mock_db.update_sequence_status.assert_called_once_with("seq-123", "PAUSED")


def test_monitor_does_not_pause_on_low_bounce(mock_db):
    mock_db.get_sequence_metrics.return_value = {
        "sends": 100,
        "bounces": 5,
        "bounce_rate": 0.05,
        "opens": 20, "interested": 3, "unsubscribes": 0,
        "open_rate": 0.20, "reply_rate": 0.03,
    }
    monitor = SequenceMonitor(mock_db, bounce_alert_threshold=0.08)
    monitor.monitor("seq-123")
    mock_db.update_sequence_status.assert_not_called()


# ---------------------------------------------------------------------------
# LeadScorer — scoring rules
# ---------------------------------------------------------------------------

def test_scorer_no_engagement_deducts_after_3_sends(mock_db, mock_crm):
    mock_db.get_lead_engagement.return_value = {"sends": 3, "opens": 0, "replies": 0, "unsubscribes": 0}
    mock_db.get_leads_by_list.return_value = [
        {"id": uuid.uuid4(), "score": 0, "status": "CONTACTED", "crm_id": None}
    ]
    scorer = LeadScorer(mock_db, mock_crm, hot_threshold=60)
    scorer.score_leads([str(uuid.uuid4())])
    mock_db.update_lead_score.assert_called_once_with(mock_db.update_lead_score.call_args[0][0], -20)


def test_scorer_unsubscribe_returns_negative_100(mock_db, mock_crm):
    mock_db.get_lead_engagement.return_value = {"sends": 2, "opens": 1, "replies": 0, "unsubscribes": 1}
    lead = {"id": uuid.uuid4(), "score": 10, "status": "CONTACTED", "crm_id": None}
    scorer = LeadScorer(mock_db, mock_crm)
    score = scorer.compute_score(lead)
    assert score == -100


def test_scorer_opens_and_reply_gives_high_score(mock_db, mock_crm):
    mock_db.get_lead_engagement.return_value = {"sends": 2, "opens": 2, "replies": 1, "unsubscribes": 0}
    lead = {"id": uuid.uuid4(), "score": 0, "status": "CONTACTED", "crm_id": None}
    scorer = LeadScorer(mock_db, mock_crm)
    score = scorer.compute_score(lead)
    assert score == 60  # 2*10 opens + 1*40 reply


def test_scorer_escalates_hot_lead(mock_db, mock_crm):
    mock_db.get_lead_engagement.return_value = {"sends": 3, "opens": 3, "replies": 1, "unsubscribes": 0}
    lead = {"id": uuid.uuid4(), "score": 0, "status": "CONTACTED", "crm_id": None,
            "email": "test@example.com", "first_name": "Jane", "last_name": "Doe",
            "company": "Acme", "research_notes": ""}
    mock_db.get_leads_by_list.return_value = [lead]
    mock_db.update_lead_score.return_value = None
    scorer = LeadScorer(mock_db, mock_crm, hot_threshold=60)
    with patch.object(scorer._queue, "push") as mock_push:
        scorer.score_leads([str(lead["id"])])
        mock_push.assert_called_once()
        assert mock_push.call_args[1]["payload"]["action"] == "handle_hot_lead"


# ---------------------------------------------------------------------------
# DomainWarmer — schedule
# ---------------------------------------------------------------------------

def test_warmer_schedule_week_0():
    w = DomainWarmer(schedule=[10, 25, 50, 100])
    assert w.get_daily_limit(0) == 10
    assert w.get_daily_limit(6) == 10


def test_warmer_schedule_week_1():
    w = DomainWarmer(schedule=[10, 25, 50, 100])
    assert w.get_daily_limit(7) == 25
    assert w.get_daily_limit(13) == 25


def test_warmer_schedule_week_3_plus():
    w = DomainWarmer(schedule=[10, 25, 50, 100])
    assert w.get_daily_limit(21) == 100
    assert w.get_daily_limit(90) == 100


# ---------------------------------------------------------------------------
# SequenceOptimizer — insufficient data guard
# ---------------------------------------------------------------------------

def test_optimizer_insufficient_data(mock_db):
    mock_db.get_sequence_metrics.return_value = {"sends": 50}
    optimizer = SequenceOptimizer(mock_db, min_sends=200)
    result = optimizer.optimize("seq-123")
    assert result["status"] == "insufficient_data"
    assert result["required"] == 200


# ---------------------------------------------------------------------------
# ForgeReporter — summary shape
# ---------------------------------------------------------------------------

def test_reporter_summary_shape(mock_db):
    mock_db.get_daily_metrics.return_value = {"sends": 100, "opens": 25, "replies": 5, "bounces": 2}
    mock_db.get_active_sequences.return_value = [
        {"id": uuid.uuid4(), "name": "OneServ Cold", "product": "oneserv", "status": "ACTIVE"}
    ]
    mock_db.count_leads_by_status.return_value = 3
    reporter = ForgeReporter(mock_db)
    summary = reporter.daily_summary()

    assert "date" in summary
    assert summary["sends_today"] == 100
    assert summary["open_rate"] == 0.25
    assert summary["reply_rate"] == 0.05
    assert len(summary["sequences"]) == 1


# ---------------------------------------------------------------------------
# SequenceLauncher — throttle logic
# ---------------------------------------------------------------------------

def test_launcher_throttle_blocked():
    db = MagicMock()
    cfg = {"hourly_send_limit": 2, "daily_send_limit": 5}
    launcher = SequenceLauncher(db, cfg)
    # Simulate hourly limit hit
    with patch.object(launcher._redis, "get", side_effect=lambda k: b"2"):
        assert launcher._can_send("alias@example.com") is False


def test_launcher_throttle_allowed():
    db = MagicMock()
    cfg = {"hourly_send_limit": 40, "daily_send_limit": 200}
    launcher = SequenceLauncher(db, cfg)
    with patch.object(launcher._redis, "get", side_effect=lambda k: b"0"):
        assert launcher._can_send("alias@example.com") is True


def test_personalize_substitutes_all_vars():
    db = MagicMock()
    cfg = {"hourly_send_limit": 40, "daily_send_limit": 200}
    launcher = SequenceLauncher(db, cfg)
    template = "Hi {first_name}, I noticed {business_name} in {city}. {specific_hook}"
    lead = {"first_name": "Jane", "company": "Acme HVAC", "city": "Austin"}
    result = launcher._personalize(template, lead, "You have great reviews.")
    assert "Jane" in result
    assert "Acme HVAC" in result
    assert "Austin" in result
    assert "You have great reviews." in result
