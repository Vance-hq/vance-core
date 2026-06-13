"""Intel agent unit tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agents.intel.community_listener import CommunityListener
from agents.intel.competitor_watcher import CompetitorWatcher
from agents.intel.db import IntelDB
from agents.intel.intel_digest import IntelDigest
from agents.intel.keyword_tracker import KeywordTracker
from agents.intel.main import IntelAgent
from agents.intel.market_shift_detector import MarketShiftDetector
from agents.intel.news_scanner import NewsScanner
from agents.intel.opportunity_scanner import OpportunityScanner
from agents.intel.press_monitor import PressMonitor
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
    agent._watcher = MagicMock(spec=CompetitorWatcher)
    agent._press = MagicMock(spec=PressMonitor)
    agent._community = MagicMock(spec=CommunityListener)
    agent._opportunities = MagicMock(spec=OpportunityScanner)
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


# ==================================================================
# NEW ACTIONS: competitor_activity_watch, press_monitoring,
#              community_listen, opportunity_scan
# ==================================================================

# ------------------------------------------------------------------
# competitor_activity_watch dispatch
# ------------------------------------------------------------------

def test_competitor_activity_watch_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("competitor_activity_watch"))
    assert result.success is False
    assert "product required" in result.output["error"]


def test_competitor_activity_watch_dispatches():
    agent = _make_agent()
    agent._watcher.run.return_value = {"product": "starpio", "competitors_checked": 3, "changes_detected": 1, "items": []}
    result = agent.handle(_make_task("competitor_activity_watch", {"product": "starpio"}))
    assert result.success is True
    agent._watcher.run.assert_called_once_with(product="starpio")


# ------------------------------------------------------------------
# press_monitoring dispatch
# ------------------------------------------------------------------

def test_press_monitoring_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("press_monitoring"))
    assert result.success is False


def test_press_monitoring_dispatches():
    agent = _make_agent()
    agent._press.run.return_value = {
        "product": "starpio", "keywords_checked": 3, "mentions_stored": 5,
        "routed_positive": 2, "routed_negative": 1,
    }
    result = agent.handle(_make_task("press_monitoring", {"product": "starpio"}))
    assert result.success is True
    assert result.output["mentions_stored"] == 5
    agent._press.run.assert_called_once_with(product="starpio")


# ------------------------------------------------------------------
# community_listen dispatch
# ------------------------------------------------------------------

def test_community_listen_requires_product():
    agent = _make_agent()
    result = agent.handle(_make_task("community_listen"))
    assert result.success is False


def test_community_listen_dispatches():
    agent = _make_agent()
    agent._community.run.return_value = {
        "product": "oneserv", "subreddits_checked": 5,
        "recommendation_requests": 3, "competitor_complaints": 1,
    }
    result = agent.handle(_make_task("community_listen", {"product": "oneserv"}))
    assert result.success is True
    assert result.output["recommendation_requests"] == 3
    agent._community.run.assert_called_once_with(product="oneserv")


# ------------------------------------------------------------------
# opportunity_scan dispatch
# ------------------------------------------------------------------

def test_opportunity_scan_dispatches():
    agent = _make_agent()
    agent._opportunities.run.return_value = {
        "opportunities_found": 8, "opportunities_saved": 8, "high_score_count": 2,
    }
    result = agent.handle(_make_task("opportunity_scan"))
    assert result.success is True
    assert result.output["high_score_count"] == 2
    agent._opportunities.run.assert_called_once()


def test_opportunity_scan_does_not_require_product():
    """opportunity_scan is monthly and product-agnostic."""
    agent = _make_agent()
    agent._opportunities.run.return_value = {"opportunities_found": 0, "opportunities_saved": 0, "high_score_count": 0}
    result = agent.handle(_make_task("opportunity_scan"))
    assert result.success is True


# ------------------------------------------------------------------
# CompetitorWatcher unit tests
# ------------------------------------------------------------------

def _make_watcher(db=None, cfg=None):
    return CompetitorWatcher(db or MagicMock(spec=IntelDB), cfg or {})


def test_watcher_no_competitors_returns_zero():
    watcher = _make_watcher(cfg={"products": {"starpio": {"competitors": [], "competitor_urls": {}}}})
    result = watcher.run("starpio")
    assert result["competitors_checked"] == 0
    assert result["changes_detected"] == 0


def test_watcher_first_check_stores_hash_no_change():
    db = MagicMock(spec=IntelDB)
    db.get_page_hash.return_value = None  # never seen before
    cfg = {
        "products": {"starpio": {
            "competitors": ["birdeye"],
            "competitor_urls": {"birdeye": {"pricing": "https://birdeye.com/pricing"}},
        }},
        "serp_api_key": "",
    }
    watcher = _make_watcher(db, cfg)
    with patch("agents.intel.competitor_watcher._fetch_page_content", return_value="<html>pricing page</html>"):
        result = watcher.run("starpio")
    db.upsert_page_hash.assert_called_once()
    db.save_competitor_activity.assert_not_called()
    assert result["changes_detected"] == 0


def test_watcher_detects_pricing_page_change():
    db = MagicMock(spec=IntelDB)
    db.get_page_hash.return_value = "oldhash1234567890"
    db.save_competitor_activity.return_value = "act-id-1"
    cfg = {
        "products": {"starpio": {
            "competitors": ["birdeye"],
            "competitor_urls": {"birdeye": {"pricing": "https://birdeye.com/pricing"}},
        }},
        "serp_api_key": "",
    }
    watcher = _make_watcher(db, cfg)
    with patch("agents.intel.competitor_watcher._fetch_page_content", return_value="<html>NEW pricing content</html>"), \
         patch("agents.intel.competitor_watcher.CompetitorWatcher._dispatch_to_reporting"):
        result = watcher.run("starpio")
    db.save_competitor_activity.assert_called_once()
    assert result["changes_detected"] == 1
    assert result["items"][0]["type"] == "pricing"


def test_watcher_no_change_same_hash():
    db = MagicMock(spec=IntelDB)
    same_content = "<html>same content</html>"
    from agents.intel.competitor_watcher import _hash_content
    db.get_page_hash.return_value = _hash_content(same_content)
    cfg = {
        "products": {"starpio": {
            "competitors": ["birdeye"],
            "competitor_urls": {"birdeye": {"pricing": "https://birdeye.com/pricing"}},
        }},
        "serp_api_key": "",
    }
    watcher = _make_watcher(db, cfg)
    with patch("agents.intel.competitor_watcher._fetch_page_content", return_value=same_content):
        result = watcher.run("starpio")
    db.save_competitor_activity.assert_not_called()
    assert result["changes_detected"] == 0


def test_watcher_blog_post_found_saves_activity():
    db = MagicMock(spec=IntelDB)
    db.get_page_hash.return_value = None
    db.save_competitor_activity.return_value = "act-blog-1"
    cfg = {
        "products": {"starpio": {
            "competitors": ["birdeye"],
            "competitor_urls": {"birdeye": {"blog": "birdeye.com/blog", "pricing": ""}},
        }},
        "serp_api_key": "fake-key",
    }
    watcher = _make_watcher(db, cfg)
    blog_results = [
        {"title": "Birdeye launches AI Reviews", "link": "https://birdeye.com/blog/ai-reviews", "snippet": "New feature"},
    ]
    # _serp_search is called for blog, linkedin, jobs, reviews — returns same result each time
    with patch("agents.intel.competitor_watcher._serp_search", return_value=blog_results), \
         patch("agents.intel.competitor_watcher.CompetitorWatcher._dispatch_to_reporting"):
        result = watcher.run("starpio")
    assert result["changes_detected"] >= 1
    activity_types = [c[1]["activity_type"] for c in db.save_competitor_activity.call_args_list]
    assert "blog_post" in activity_types


def test_watcher_job_listing_found_saves_activity():
    db = MagicMock(spec=IntelDB)
    db.get_page_hash.return_value = None
    db.save_competitor_activity.return_value = "act-job-1"
    cfg = {
        "products": {"starpio": {
            "competitors": ["birdeye"],
            "competitor_urls": {"birdeye": {}},
        }},
        "serp_api_key": "fake-key",
    }
    watcher = _make_watcher(db, cfg)
    job_results = [{"title": "Birdeye — Senior Engineer", "link": "https://linkedin.com/jobs/123", "snippet": "Join our team"}]
    with patch("agents.intel.competitor_watcher._serp_search", return_value=job_results), \
         patch("agents.intel.competitor_watcher.CompetitorWatcher._dispatch_to_reporting"):
        result = watcher.run("starpio")
    assert any(i["type"] == "job_listing" for i in result["items"])


def test_watcher_dispatches_to_reporting_when_changes_found():
    db = MagicMock(spec=IntelDB)
    db.get_page_hash.return_value = "old"
    db.save_competitor_activity.return_value = "act-123"
    cfg = {
        "products": {"starpio": {
            "competitors": ["birdeye"],
            "competitor_urls": {"birdeye": {"pricing": "https://birdeye.com/pricing"}},
        }},
        "serp_api_key": "",
    }
    watcher = _make_watcher(db, cfg)
    with patch("agents.intel.competitor_watcher._fetch_page_content", return_value="<html>changed</html>"), \
         patch("agents.intel.competitor_watcher.TaskQueue") as MockQ:
        watcher.run("starpio")
    MockQ.return_value.push.assert_called_once()


def test_watcher_fetch_error_handled_gracefully():
    db = MagicMock(spec=IntelDB)
    db.get_page_hash.return_value = None
    cfg = {
        "products": {"starpio": {
            "competitors": ["birdeye"],
            "competitor_urls": {"birdeye": {"pricing": "https://birdeye.com/pricing"}},
        }},
        "serp_api_key": "",
    }
    watcher = _make_watcher(db, cfg)
    with patch("agents.intel.competitor_watcher._fetch_page_content", side_effect=Exception("timeout")):
        result = watcher.run("starpio")
    assert result["changes_detected"] == 0


# ------------------------------------------------------------------
# PressMonitor unit tests
# ------------------------------------------------------------------

def _make_press(db=None, cfg=None):
    return PressMonitor(db or MagicMock(spec=IntelDB), cfg or {})


def test_press_monitor_no_keywords_returns_zero():
    monitor = _make_press(cfg={"products": {"starpio": {"press_keywords": []}}})
    result = monitor.run("starpio")
    assert result["mentions_stored"] == 0


def test_press_monitor_positive_mention_routes_to_content():
    db = MagicMock(spec=IntelDB)
    db.save_press_mention.return_value = "pm-001"
    cfg = {
        "serp_api_key": "fake",
        "products": {"starpio": {"press_keywords": ["Starpio review"]}},
    }
    monitor = _make_press(db, cfg)
    articles = [{"title": "Starpio wins best review tool", "source": "TechCrunch", "link": "https://tc.co/1", "snippet": "Great product"}]
    with patch("agents.intel.press_monitor._search_news", return_value=articles), \
         patch("agents.intel.press_monitor.PressMonitor._classify_sentiment", return_value="positive"), \
         patch("agents.intel.press_monitor.TaskQueue") as MockQ:
        result = monitor.run("starpio")
    assert result["routed_positive"] == 1
    MockQ.return_value.push.assert_called()


def test_press_monitor_negative_mention_routes_to_strategy():
    db = MagicMock(spec=IntelDB)
    db.save_press_mention.return_value = "pm-002"
    cfg = {
        "serp_api_key": "fake",
        "products": {"starpio": {"press_keywords": ["Starpio"]}},
    }
    monitor = _make_press(db, cfg)
    articles = [{"title": "Starpio outage angers customers", "source": "Hacker News", "link": "https://hn.co/1", "snippet": "Many users lost data"}]
    with patch("agents.intel.press_monitor._search_news", return_value=articles), \
         patch("agents.intel.press_monitor.PressMonitor._classify_sentiment", return_value="negative"), \
         patch("agents.intel.press_monitor.TaskQueue") as MockQ:
        result = monitor.run("starpio")
    assert result["routed_negative"] == 1
    call_args = MockQ.return_value.push.call_args
    assert call_args[0][0] == "strategy"


def test_press_monitor_neutral_mention_stored_not_routed():
    db = MagicMock(spec=IntelDB)
    db.save_press_mention.return_value = "pm-003"
    cfg = {
        "serp_api_key": "fake",
        "products": {"starpio": {"press_keywords": ["review management"]}},
    }
    monitor = _make_press(db, cfg)
    articles = [{"title": "Review management market overview", "source": "G2", "link": "https://g2.com/1", "snippet": "Various tools compared"}]
    with patch("agents.intel.press_monitor._search_news", return_value=articles), \
         patch("agents.intel.press_monitor.PressMonitor._classify_sentiment", return_value="neutral"), \
         patch("agents.intel.press_monitor.TaskQueue") as MockQ:
        result = monitor.run("starpio")
    assert result["mentions_stored"] == 1
    assert result["routed_positive"] == 0
    assert result["routed_negative"] == 0
    MockQ.return_value.push.assert_not_called()


def test_press_monitor_duplicate_url_not_stored_twice():
    db = MagicMock(spec=IntelDB)
    db.save_press_mention.return_value = None  # duplicate
    cfg = {
        "serp_api_key": "fake",
        "products": {"starpio": {"press_keywords": ["Starpio"]}},
    }
    monitor = _make_press(db, cfg)
    articles = [{"title": "Old article", "source": "Blog", "link": "https://already-seen.com/1", "snippet": "..."}]
    with patch("agents.intel.press_monitor._search_news", return_value=articles), \
         patch("agents.intel.press_monitor.PressMonitor._classify_sentiment", return_value="positive"), \
         patch("agents.intel.press_monitor.TaskQueue") as MockQ:
        result = monitor.run("starpio")
    assert result["mentions_stored"] == 0
    MockQ.return_value.push.assert_not_called()


def test_press_monitor_sentiment_classifier_returns_valid_value():
    monitor = _make_press()
    with patch("agents.intel.press_monitor.llm") as mock_llm:
        mock_llm.complete.return_value.content = [MagicMock(text="positive")]
        sentiment = monitor._classify_sentiment("Great product launch", "Users love the new feature")
    assert sentiment in {"positive", "negative", "neutral"}


def test_press_monitor_sentiment_fallback_on_llm_error():
    monitor = _make_press()
    with patch("agents.intel.press_monitor.llm") as mock_llm:
        mock_llm.complete.side_effect = Exception("LLM timeout")
        sentiment = monitor._classify_sentiment("Some headline", "Some snippet")
    assert sentiment == "neutral"


# ------------------------------------------------------------------
# CommunityListener unit tests
# ------------------------------------------------------------------

def _make_listener(db=None, cfg=None):
    return CommunityListener(db or MagicMock(spec=IntelDB), cfg or {})


def test_community_listener_recommendation_post_routes_to_outreach():
    db = MagicMock(spec=IntelDB)
    db.save_community_signal.return_value = "cs-001"
    cfg = {
        "subreddits": ["smallbusiness"],
        "products": {"starpio": {"competitors": ["birdeye"], "keywords": ["review management"]}},
    }
    listener = _make_listener(db, cfg)
    posts = [{"title": "Looking for the best review management tool", "selftext": "recommendations please", "permalink": "/r/smallbusiness/1", "score": 50}]
    with patch("agents.intel.community_listener._fetch_reddit_posts", return_value=posts), \
         patch("agents.intel.community_listener.TaskQueue") as MockQ:
        result = listener.run("starpio")
    assert result["recommendation_requests"] == 1
    call_args = MockQ.return_value.push.call_args
    assert call_args[0][0] == "outreach"


def test_community_listener_competitor_complaint_routes_to_content():
    db = MagicMock(spec=IntelDB)
    db.save_community_signal.return_value = "cs-002"
    cfg = {
        "subreddits": ["SaaS"],
        "products": {"starpio": {"competitors": ["birdeye"], "keywords": ["review management"]}},
    }
    listener = _make_listener(db, cfg)
    posts = [{"title": "Hate birdeye - canceled after terrible support", "selftext": "switched away", "permalink": "/r/SaaS/2", "score": 80}]
    with patch("agents.intel.community_listener._fetch_reddit_posts", return_value=posts), \
         patch("agents.intel.community_listener.TaskQueue") as MockQ:
        result = listener.run("starpio")
    assert result["competitor_complaints"] == 1
    call_args = MockQ.return_value.push.call_args
    assert call_args[0][0] == "content"


def test_community_listener_irrelevant_post_not_stored():
    db = MagicMock(spec=IntelDB)
    cfg = {
        "subreddits": ["Entrepreneur"],
        "products": {"starpio": {"competitors": [], "keywords": []}},
    }
    listener = _make_listener(db, cfg)
    posts = [{"title": "How to hire my first employee", "selftext": "tips please", "permalink": "/r/Entrepreneur/3", "score": 10}]
    with patch("agents.intel.community_listener._fetch_reddit_posts", return_value=posts):
        result = listener.run("starpio")
    db.save_community_signal.assert_not_called()
    assert result["recommendation_requests"] == 0


def test_community_listener_deduplication_skips_existing():
    db = MagicMock(spec=IntelDB)
    db.save_community_signal.return_value = None  # duplicate
    cfg = {
        "subreddits": ["msp"],
        "products": {"starpio": {"competitors": [], "keywords": ["review management"]}},
    }
    listener = _make_listener(db, cfg)
    posts = [{"title": "Looking for review management tool", "selftext": "", "permalink": "/r/msp/4", "score": 5}]
    with patch("agents.intel.community_listener._fetch_reddit_posts", return_value=posts), \
         patch("agents.intel.community_listener.TaskQueue") as MockQ:
        result = listener.run("starpio")
    MockQ.return_value.push.assert_not_called()


def test_community_listener_checks_all_configured_subreddits():
    db = MagicMock(spec=IntelDB)
    db.save_community_signal.return_value = None
    cfg = {
        "subreddits": ["msp", "SaaS", "Plumbing"],
        "products": {"starpio": {"competitors": [], "keywords": []}},
    }
    listener = _make_listener(db, cfg)
    with patch("agents.intel.community_listener._fetch_reddit_posts", return_value=[]) as mock_fetch:
        result = listener.run("starpio")
    assert mock_fetch.call_count == 3
    assert result["subreddits_checked"] == 3


def test_community_listener_facebook_recommendation_routes_to_outreach():
    db = MagicMock(spec=IntelDB)
    db.save_community_signal.return_value = "cs-fb-001"
    cfg = {
        "subreddits": [],
        "apify_facebook_run_id": "run-123",
        "apify_api_token": "token-abc",
        "products": {"starpio": {"competitors": [], "keywords": ["review management"]}},
    }
    listener = _make_listener(db, cfg)
    fb_posts = [{"text": "Anyone have recommendations for review management software?", "url": "https://fb.com/groups/post/1"}]
    with patch("agents.intel.community_listener._fetch_apify_facebook", return_value=fb_posts), \
         patch("agents.intel.community_listener.TaskQueue") as MockQ:
        result = listener.run("starpio")
    assert result["recommendation_requests"] == 1
    MockQ.return_value.push.assert_called()


# ------------------------------------------------------------------
# OpportunityScanner unit tests
# ------------------------------------------------------------------

def _make_scanner(db=None, cfg=None):
    return OpportunityScanner(db or MagicMock(spec=IntelDB), cfg or {})


def test_opportunity_scanner_high_score_routes_to_strategy():
    db = MagicMock(spec=IntelDB)
    db.save_opportunity.return_value = "opp-001"
    cfg = {"serp_api_key": "fake", "opportunity_keywords": ["review management"]}
    scanner = _make_scanner(db, cfg)

    ph_results = [{"type": "product_hunt", "description": "ReviewBot AI — automate review replies", "source_url": "https://ph.co/1", "snippet": "Top product this week"}]
    scoring = {"score": 9, "relevance": 9, "effort": "low", "potential_impact": "high", "rationale": "Direct competitor and high traction"}

    with patch("agents.intel.opportunity_scanner._fetch_product_hunt", return_value=ph_results), \
         patch("agents.intel.opportunity_scanner._fetch_api_integrations", return_value=[]), \
         patch("agents.intel.opportunity_scanner._fetch_affiliate_partners", return_value=[]), \
         patch("agents.intel.opportunity_scanner.OpportunityScanner._score_opportunity", return_value=scoring), \
         patch("agents.intel.opportunity_scanner.TaskQueue") as MockQ:
        result = scanner.run()

    assert result["high_score_count"] == 1
    MockQ.return_value.push.assert_called_once()
    call_args = MockQ.return_value.push.call_args
    assert call_args[0][0] == "strategy"


def test_opportunity_scanner_low_score_stored_not_routed():
    db = MagicMock(spec=IntelDB)
    db.save_opportunity.return_value = "opp-002"
    cfg = {"serp_api_key": "fake", "opportunity_keywords": []}
    scanner = _make_scanner(db, cfg)

    ph_results = [{"type": "product_hunt", "description": "Unrelated SaaS tool", "source_url": "https://ph.co/2", "snippet": "Niche product"}]
    scoring = {"score": 3, "relevance": 3, "effort": "high", "potential_impact": "low", "rationale": "Not relevant"}

    with patch("agents.intel.opportunity_scanner._fetch_product_hunt", return_value=ph_results), \
         patch("agents.intel.opportunity_scanner._fetch_api_integrations", return_value=[]), \
         patch("agents.intel.opportunity_scanner._fetch_affiliate_partners", return_value=[]), \
         patch("agents.intel.opportunity_scanner.OpportunityScanner._score_opportunity", return_value=scoring), \
         patch("agents.intel.opportunity_scanner.TaskQueue") as MockQ:
        result = scanner.run()

    assert result["high_score_count"] == 0
    db.save_opportunity.assert_called_once()
    MockQ.return_value.push.assert_not_called()


def test_opportunity_scanner_parses_llm_json_score():
    db = MagicMock(spec=IntelDB)
    scanner = _make_scanner(db)
    opp = {"type": "product_hunt", "description": "Great tool", "snippet": "Relevant", "source_url": ""}
    import json
    scoring_json = json.dumps({
        "score": 8, "relevance": 9, "effort": "low", "potential_impact": "high",
        "rationale": "Strong match for our market",
    })
    with patch("agents.intel.opportunity_scanner.llm") as mock_llm:
        mock_llm.complete.return_value.content = [MagicMock(text=scoring_json)]
        result = scanner._score_opportunity(opp)
    assert result["score"] == 8
    assert result["effort"] == "low"


def test_opportunity_scanner_handles_llm_parse_error_gracefully():
    db = MagicMock(spec=IntelDB)
    scanner = _make_scanner(db)
    opp = {"type": "affiliate", "description": "Some tool", "snippet": "", "source_url": ""}
    with patch("agents.intel.opportunity_scanner.llm") as mock_llm:
        mock_llm.complete.return_value.content = [MagicMock(text="not valid json {{ broken")]
        result = scanner._score_opportunity(opp)
    assert result["score"] == 5  # default fallback


def test_opportunity_scanner_empty_results_returns_zero():
    db = MagicMock(spec=IntelDB)
    cfg = {"serp_api_key": "", "opportunity_keywords": []}
    scanner = _make_scanner(db, cfg)
    with patch("agents.intel.opportunity_scanner._fetch_product_hunt", return_value=[]), \
         patch("agents.intel.opportunity_scanner._fetch_api_integrations", return_value=[]), \
         patch("agents.intel.opportunity_scanner._fetch_affiliate_partners", return_value=[]):
        result = scanner.run()
    assert result["opportunities_found"] == 0
    assert result["high_score_count"] == 0


def test_opportunity_scanner_returns_correct_counts():
    db = MagicMock(spec=IntelDB)
    db.save_opportunity.return_value = "opp-x"
    cfg = {"serp_api_key": "key", "opportunity_keywords": []}
    scanner = _make_scanner(db, cfg)

    items = [
        {"type": "product_hunt", "description": "A", "source_url": "", "snippet": ""},
        {"type": "api_integration", "description": "B", "source_url": "", "snippet": ""},
        {"type": "affiliate", "description": "C", "source_url": "", "snippet": ""},
    ]
    scoring = {"score": 4, "relevance": 4, "effort": "medium", "potential_impact": "medium", "rationale": ""}

    with patch("agents.intel.opportunity_scanner._fetch_product_hunt", return_value=[items[0]]), \
         patch("agents.intel.opportunity_scanner._fetch_api_integrations", return_value=[items[1]]), \
         patch("agents.intel.opportunity_scanner._fetch_affiliate_partners", return_value=[items[2]]), \
         patch("agents.intel.opportunity_scanner.OpportunityScanner._score_opportunity", return_value=scoring), \
         patch("agents.intel.opportunity_scanner.TaskQueue"):
        result = scanner.run()

    assert result["opportunities_found"] == 3
    assert result["opportunities_saved"] == 3
    assert db.save_opportunity.call_count == 3


# ------------------------------------------------------------------
# IntelDB — new methods structural tests
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


def test_db_save_competitor_activity():
    db = IntelDB()
    with patch("agents.intel.db.get_db", return_value=_mock_db_conn(fetchone_val={"id": "act-id"})):
        result = db.save_competitor_activity("birdeye", "pricing_change", "Price dropped 20%", product="starpio")
    assert result == "act-id"


def test_db_save_press_mention_returns_none_on_duplicate():
    db = IntelDB()
    with patch("agents.intel.db.get_db", return_value=_mock_db_conn(fetchone_val=None)):
        result = db.save_press_mention("Starpio", "Article", "TC", "https://dup.com/1")
    assert result is None


def test_db_save_press_mention_returns_id_on_new():
    db = IntelDB()
    with patch("agents.intel.db.get_db", return_value=_mock_db_conn(fetchone_val={"id": "pm-id"})):
        result = db.save_press_mention("Starpio", "New article", "TC", "https://new.com/1", sentiment="positive")
    assert result == "pm-id"


def test_db_save_community_signal_duplicate_returns_none():
    db = IntelDB()
    with patch("agents.intel.db.get_db", return_value=_mock_db_conn(fetchone_val=None)):
        result = db.save_community_signal("reddit", "https://reddit.com/dup", "recommendation_request", "Some post")
    assert result is None


def test_db_save_opportunity():
    db = IntelDB()
    with patch("agents.intel.db.get_db", return_value=_mock_db_conn(fetchone_val={"id": "opp-id"})):
        result = db.save_opportunity("product_hunt", "New AI tool", score=8, relevance=9)
    assert result == "opp-id"


def test_db_get_page_hash_returns_none_when_missing():
    db = IntelDB()
    with patch("agents.intel.db.get_db", return_value=_mock_db_conn(fetchone_val=None)):
        result = db.get_page_hash("birdeye", "pricing")
    assert result is None


def test_db_get_page_hash_returns_stored_hash():
    db = IntelDB()
    with patch("agents.intel.db.get_db", return_value=_mock_db_conn(fetchone_val={"content_hash": "abc123"})):
        result = db.get_page_hash("birdeye", "pricing")
    assert result == "abc123"
