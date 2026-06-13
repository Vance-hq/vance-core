"""Intel agent unit tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agents.intel.db import IntelDB
from agents.intel.intel_digest import IntelDigest
from agents.intel.keyword_tracker import KeywordTracker
from agents.intel.main import IntelAgent
from agents.intel.market_shift_detector import MarketShiftDetector
from agents.intel.news_scanner import NewsScanner
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


def _make_agent(cfg: dict | None = None) -> IntelAgent:
    config = MagicMock()
    config.custom = cfg or {}
    config.llm_system_prompt = ""
    config.poll_interval_seconds = 10

    agent = IntelAgent.__new__(IntelAgent)
    agent.agent_name = "intel"
    agent.config = config
    agent._db = MagicMock(spec=IntelDB)
    agent._keywords = MagicMock()
    agent._news = MagicMock()
    agent._social = MagicMock()
    agent._shifts = MagicMock()
    agent._digest = MagicMock()
    return agent


# ------------------------------------------------------------------
# Dispatch
# ------------------------------------------------------------------

def test_unknown_action_returns_failure():
    agent = _make_agent()
    result = agent.handle(_make_task("not_real"))
    assert result.success is False
    assert "Unknown intel action" in result.output["error"]


def test_track_keyword_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("track_keyword"))
    assert result.success is False


def test_track_keyword_dispatches():
    agent = _make_agent()
    agent._keywords.run.return_value = {"product": "starpio", "keywords_tracked": 3}
    result = agent.handle(_make_task("track_keyword", {"product": "starpio"}))
    assert result.success is True
    agent._keywords.run.assert_called_once_with(product="starpio")


def test_scan_industry_news_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("scan_industry_news"))
    assert result.success is False


def test_scan_industry_news_dispatches():
    agent = _make_agent()
    agent._news.run.return_value = {"product": "starpio", "signals_found": 5}
    result = agent.handle(_make_task("scan_industry_news", {"product": "starpio"}))
    assert result.success is True


def test_monitor_competitors_social_dispatches():
    agent = _make_agent()
    agent._social.run.return_value = {"product": "oneserv", "competitors_scanned": 3}
    result = agent.handle(_make_task("monitor_competitors_social", {"product": "oneserv"}))
    assert result.success is True


def test_detect_market_shift_dispatches():
    agent = _make_agent()
    agent._shifts.run.return_value = {"product": "starpio", "shifts_detected": 1}
    result = agent.handle(_make_task("detect_market_shift", {"product": "starpio"}))
    assert result.success is True


def test_digest_intel_no_product_required():
    agent = _make_agent()
    agent._digest.run.return_value = {"signals_found": 4}
    result = agent.handle(_make_task("digest_intel"))
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
# KeywordTracker
# ------------------------------------------------------------------

def test_keyword_tracker_no_keywords_returns_zero():
    db = MagicMock(spec=IntelDB)
    db.list_keyword_trends.return_value = []
    tracker = KeywordTracker(db, {"products": {"starpio": {"keywords": []}}})
    result = tracker.run("starpio")
    assert result["keywords_tracked"] == 0


def test_keyword_tracker_detects_rising_trend():
    db = MagicMock(spec=IntelDB)
    db.list_keyword_trends.return_value = [
        {"keyword": "review automation", "volume_index": 100, "trend_direction": "stable"}
    ]
    cfg = {"products": {"starpio": {"keywords": ["review automation"]}}}
    tracker = KeywordTracker(db, cfg)

    with patch("agents.intel.keyword_tracker._get_keyword_volume", return_value=150), \
         patch("agents.intel.keyword_tracker.TaskQueue") as MockQ:
        result = tracker.run("starpio")

    assert any(m["direction"] == "rising" for m in result["significant_movements"])
    MockQ.return_value.push.assert_called_once()


def test_keyword_tracker_stable_no_notify():
    db = MagicMock(spec=IntelDB)
    db.list_keyword_trends.return_value = [
        {"keyword": "review automation", "volume_index": 100, "trend_direction": "stable"}
    ]
    cfg = {"products": {"starpio": {"keywords": ["review automation"]}}}
    tracker = KeywordTracker(db, cfg)

    with patch("agents.intel.keyword_tracker._get_keyword_volume", return_value=105), \
         patch("agents.intel.keyword_tracker.TaskQueue") as MockQ:
        result = tracker.run("starpio")

    assert result["significant_movements"] == []
    MockQ.return_value.push.assert_not_called()


def test_keyword_tracker_detects_falling():
    db = MagicMock(spec=IntelDB)
    db.list_keyword_trends.return_value = [
        {"keyword": "gbp management", "volume_index": 200, "trend_direction": "rising"}
    ]
    cfg = {"products": {"starpio": {"keywords": ["gbp management"]}}}
    tracker = KeywordTracker(db, cfg)

    with patch("agents.intel.keyword_tracker._get_keyword_volume", return_value=100), \
         patch("agents.intel.keyword_tracker.TaskQueue"):
        result = tracker.run("starpio")

    assert any(m["direction"] == "falling" for m in result["significant_movements"])


# ------------------------------------------------------------------
# NewsScanner
# ------------------------------------------------------------------

def test_news_scanner_no_results_returns_zero():
    db = MagicMock(spec=IntelDB)
    cfg = {"products": {"starpio": {"keywords": ["review automation"]}}}
    scanner = NewsScanner(db, cfg)
    with patch("agents.intel.news_scanner._web_search", return_value=[]):
        result = scanner.run("starpio")
    assert result["signals_found"] == 0


def test_news_scanner_stores_signals_and_notifies_high():
    db = MagicMock(spec=IntelDB)
    db.save_signal.return_value = "sig-id"
    cfg = {"products": {"starpio": {"keywords": ["review automation"]}}}
    scanner = NewsScanner(db, cfg)

    fake_results = [{"title": "Birdeye raises $150M", "snippet": "Series D funding", "url": "https://t.co/x"}]
    scored = [{"headline": "Birdeye raises $150M", "relevance": 9, "summary": "Competitor funding", "url": ""}]

    with patch("agents.intel.news_scanner._web_search", return_value=fake_results), \
         patch("agents.intel.news_scanner.llm") as mock_llm, \
         patch("agents.intel.news_scanner.TaskQueue") as MockQ:
        import json
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(scored))]
        result = scanner.run("starpio")

    assert result["high_relevance"] == 1
    db.save_signal.assert_called_once()
    MockQ.return_value.push.assert_called_once()


def test_news_scanner_low_relevance_no_strategy_notify():
    db = MagicMock(spec=IntelDB)
    db.save_signal.return_value = "sig-id"
    cfg = {"products": {"starpio": {"keywords": ["review automation"]}}}
    scanner = NewsScanner(db, cfg)

    scored = [{"headline": "Small news", "relevance": 3, "summary": "minor", "url": ""}]
    with patch("agents.intel.news_scanner._web_search", return_value=[{"title": "x", "snippet": "y", "url": ""}]), \
         patch("agents.intel.news_scanner.llm") as mock_llm, \
         patch("agents.intel.news_scanner.TaskQueue") as MockQ:
        import json
        mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(scored))]
        result = scanner.run("starpio")

    assert result["high_relevance"] == 0
    MockQ.return_value.push.assert_not_called()


# ------------------------------------------------------------------
# IntelDigest
# ------------------------------------------------------------------

def test_intel_digest_enqueues_reporting():
    db = MagicMock(spec=IntelDB)
    db.list_signals.return_value = [{"headline": "Signal 1", "relevance_score": 8}]
    db.list_keyword_trends.return_value = [{"keyword": "review automation"}]
    digest = IntelDigest(db, {})
    with patch("agents.intel.intel_digest.TaskQueue") as MockQ:
        result = digest.run("starpio")
    MockQ.return_value.push.assert_called_once()
    assert result["total_signals_today"] == 1


def test_intel_digest_handles_empty_signals():
    db = MagicMock(spec=IntelDB)
    db.list_signals.return_value = []
    db.list_keyword_trends.return_value = []
    digest = IntelDigest(db, {})
    with patch("agents.intel.intel_digest.TaskQueue"):
        result = digest.run("starpio")
    assert result["total_signals_today"] == 0


# ------------------------------------------------------------------
# MarketShiftDetector
# ------------------------------------------------------------------

def test_market_shift_no_competitors_returns_empty():
    db = MagicMock(spec=IntelDB)
    cfg = {"products": {"starpio": {"competitors": []}}}
    detector = MarketShiftDetector(db, cfg)
    result = detector.run("starpio")
    assert result["shifts_detected"] == 0


def test_market_shift_notifies_strategy_when_shifts_found():
    db = MagicMock(spec=IntelDB)
    db.save_signal.return_value = "sig-id"
    cfg = {"products": {"starpio": {"competitors": ["birdeye"]}}}
    detector = MarketShiftDetector(db, cfg)

    import json
    shift_data = {"shifts_detected": True, "shifts": [{"type": "pricing", "description": "Birdeye dropped price 20%", "impact": "high"}]}
    with patch("agents.intel.market_shift_detector.llm") as mock_llm, \
         patch("agents.intel.market_shift_detector.TaskQueue") as MockQ:
        try:
            from shared.search import search as _search
        except Exception:
            pass
        with patch("agents.intel.market_shift_detector.MarketShiftDetector._detect_shifts", return_value=shift_data["shifts"]):
            result = detector.run("starpio")

    assert result["shifts_detected"] == 1
    MockQ.return_value.push.assert_called_once()


# ------------------------------------------------------------------
# IntelDB structural
# ------------------------------------------------------------------

def test_intel_db_save_signal_calls_get_db():
    db = IntelDB()
    with patch("agents.intel.db.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {"id": "sig-id"}
        mock_conn.cursor.return_value = mock_cur
        mock_get_db.return_value = mock_conn
        result = db.save_signal("news", "Test headline", product="starpio")
    assert result == "sig-id"
