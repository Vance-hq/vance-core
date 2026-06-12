"""Research agent unit tests — no external services required."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agents._base import AgentConfig
from agents.research.db import ResearchDB
from agents.research.competitor_monitor import CompetitorMonitor
from agents.research.market_signal_scan import MarketSignalScan
from agents.research.customer_sentiment import CustomerSentiment
from agents.research.feature_gap_analysis import FeatureGapAnalysis
from agents.research.pricing_research import PricingResearch
from shared.types import AgentCapability, Task, TaskResult


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _snapshot(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "product": "starpio",
        "competitor": "birdeye",
        "snapshot_date": datetime.now(timezone.utc).date().isoformat(),
        "changes_detected": True,
        "summary": "New pricing tier added at $199/mo.",
    }
    if overrides:
        base.update(overrides)
    return base


def _signal(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "product": "starpio",
        "source": "google_news",
        "headline": "Google releases new review management API",
        "relevance_score": 8,
        "detected_at": datetime.now(timezone.utc),
        "actioned": False,
    }
    if overrides:
        base.update(overrides)
    return base


def _gap(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "product": "starpio",
        "feature": "bulk_review_response",
        "competitor_coverage": 3,
        "customer_demand_score": 7,
        "status": "proposed",
    }
    if overrides:
        base.update(overrides)
    return base


@pytest.fixture
def mock_db():
    db = MagicMock(spec=ResearchDB)
    db.save_snapshot.return_value = str(uuid.uuid4())
    db.get_latest_snapshot.return_value = _snapshot()
    db.save_signal.return_value = str(uuid.uuid4())
    db.list_signals.return_value = [_signal()]
    db.save_feature_gap.return_value = str(uuid.uuid4())
    db.list_feature_gaps.return_value = [_gap()]
    db.get_sentiment_inputs.return_value = {
        "tickets": ["App crashes on submit", "Love the auto-responses"],
        "nps_comments": ["Wish it worked on Yelp too"],
        "review_text": ["Easy to use but limited integrations"],
    }
    return db


@pytest.fixture
def cfg() -> dict:
    return {
        "serper_api_key": "serper_test_key",
        "reddit_client_id": "reddit_id",
        "reddit_client_secret": "reddit_secret",
        "products": {
            "starpio": {
                "name": "Starpio",
                "competitors": ["birdeye", "podium", "grade_us"],
                "keywords": ["google review management", "review automation", "GBP replies"],
                "feature_set": ["ai_responses", "review_monitoring", "gbp_integration", "sms_alerts"],
            },
            "oneserv": {
                "name": "Oneserv",
                "competitors": ["jobber", "housecall_pro"],
                "keywords": ["field service management", "job dispatch software"],
                "feature_set": ["job_creation", "dispatch", "invoicing", "crew_management"],
            },
            "localoutrank": {
                "name": "LocalOutRank",
                "competitors": ["brightlocal", "whitespark"],
                "keywords": ["local seo audit", "GMB optimization tool"],
                "feature_set": ["seo_audit", "citation_tracking", "gbp_optimizer", "rank_tracker"],
            },
        },
    }


# ---------------------------------------------------------------------------
# ResearchDB
# ---------------------------------------------------------------------------

class TestResearchDB:

    def _make_db_with_mock_conn(self):
        db = ResearchDB.__new__(ResearchDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        return db, mock_conn, mock_cur

    def test_save_snapshot_returns_id(self):
        db, mock_conn, mock_cur = self._make_db_with_mock_conn()
        expected_id = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected_id}
        with patch("agents.research.db.get_db", return_value=mock_conn):
            result = db.save_snapshot(
                product="starpio",
                competitor="birdeye",
                changes_detected=True,
                summary="New pricing page",
                raw_content="pricing content...",
            )
        assert result == expected_id

    def test_get_latest_snapshot_returns_dict(self):
        db, mock_conn, mock_cur = self._make_db_with_mock_conn()
        mock_cur.fetchone.return_value = _snapshot()
        with patch("agents.research.db.get_db", return_value=mock_conn):
            result = db.get_latest_snapshot(product="starpio", competitor="birdeye")
        assert result is not None
        assert result["competitor"] == "birdeye"

    def test_get_latest_snapshot_returns_none_when_missing(self):
        db, mock_conn, mock_cur = self._make_db_with_mock_conn()
        mock_cur.fetchone.return_value = None
        with patch("agents.research.db.get_db", return_value=mock_conn):
            result = db.get_latest_snapshot(product="starpio", competitor="unknown")
        assert result is None

    def test_save_signal_returns_id(self):
        db, mock_conn, mock_cur = self._make_db_with_mock_conn()
        expected_id = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected_id}
        with patch("agents.research.db.get_db", return_value=mock_conn):
            result = db.save_signal(
                product="starpio",
                source="google_news",
                headline="New API released",
                relevance_score=8,
                url="https://example.com/article",
            )
        assert result == expected_id

    def test_save_feature_gap_returns_id(self):
        db, mock_conn, mock_cur = self._make_db_with_mock_conn()
        expected_id = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected_id}
        with patch("agents.research.db.get_db", return_value=mock_conn):
            result = db.save_feature_gap(
                product="starpio",
                feature="bulk_response",
                competitor_coverage=3,
                customer_demand_score=7,
            )
        assert result == expected_id

    def test_list_signals_high_relevance_only(self):
        db, mock_conn, mock_cur = self._make_db_with_mock_conn()
        mock_cur.fetchall.return_value = [_signal({"relevance_score": 9})]
        with patch("agents.research.db.get_db", return_value=mock_conn):
            results = db.list_signals(product="starpio", min_relevance=7)
        assert len(results) == 1
        assert results[0]["relevance_score"] == 9


# ---------------------------------------------------------------------------
# CompetitorMonitor
# ---------------------------------------------------------------------------

class TestCompetitorMonitor:

    def test_monitor_runs_for_each_competitor(self, mock_db, cfg):
        monitor = CompetitorMonitor(mock_db, cfg)
        with patch("agents.research.competitor_monitor.web_search") as mock_search, \
             patch("agents.research.competitor_monitor.llm") as mock_llm, \
             patch("agents.research.competitor_monitor.enqueue_strategy_signal"):
            mock_search.return_value = [{"title": "BirdEye raises prices", "snippet": "..."}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "changes_detected": True,
                    "summary": "New pricing tier at $199/mo",
                    "recommended_response": "Maintain current pricing, highlight value",
                }))
            ]
            mock_db.get_latest_snapshot.return_value = None
            result = monitor.run(product="starpio")
        assert result["product"] == "starpio"
        assert result["competitors_scanned"] == 3

    def test_monitor_saves_snapshot_per_competitor(self, mock_db, cfg):
        monitor = CompetitorMonitor(mock_db, cfg)
        with patch("agents.research.competitor_monitor.web_search") as mock_search, \
             patch("agents.research.competitor_monitor.llm") as mock_llm, \
             patch("agents.research.competitor_monitor.enqueue_strategy_signal"):
            mock_search.return_value = [{"title": "Feature launch", "snippet": "new AI feature"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "changes_detected": True,
                    "summary": "New AI feature launched",
                    "recommended_response": "Accelerate our AI roadmap",
                }))
            ]
            mock_db.get_latest_snapshot.return_value = None
            monitor.run(product="starpio")
        assert mock_db.save_snapshot.call_count == 3

    def test_monitor_signals_strategy_on_significant_change(self, mock_db, cfg):
        monitor = CompetitorMonitor(mock_db, cfg)
        with patch("agents.research.competitor_monitor.web_search") as mock_search, \
             patch("agents.research.competitor_monitor.llm") as mock_llm, \
             patch("agents.research.competitor_monitor.enqueue_strategy_signal") as mock_signal:
            mock_search.return_value = [{"title": "Podium acquires competitor", "snippet": "major acquisition"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "changes_detected": True,
                    "summary": "Major acquisition detected",
                    "recommended_response": "Reposition our differentiation",
                }))
            ]
            mock_db.get_latest_snapshot.return_value = None
            monitor.run(product="starpio")
        assert mock_signal.call_count >= 1

    def test_monitor_no_signal_when_no_changes(self, mock_db, cfg):
        monitor = CompetitorMonitor(mock_db, cfg)
        with patch("agents.research.competitor_monitor.web_search") as mock_search, \
             patch("agents.research.competitor_monitor.llm") as mock_llm, \
             patch("agents.research.competitor_monitor.enqueue_strategy_signal") as mock_signal:
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "changes_detected": False,
                    "summary": "No significant changes",
                    "recommended_response": "",
                }))
            ]
            mock_db.get_latest_snapshot.return_value = None
            monitor.run(product="starpio")
        mock_signal.assert_not_called()

    def test_monitor_result_has_required_keys(self, mock_db, cfg):
        monitor = CompetitorMonitor(mock_db, cfg)
        with patch("agents.research.competitor_monitor.web_search") as mock_search, \
             patch("agents.research.competitor_monitor.llm") as mock_llm, \
             patch("agents.research.competitor_monitor.enqueue_strategy_signal"):
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({"changes_detected": False, "summary": "", "recommended_response": ""}))
            ]
            mock_db.get_latest_snapshot.return_value = None
            result = monitor.run(product="starpio")
        for key in ("product", "competitors_scanned", "changes_found", "snapshots"):
            assert key in result

    def test_monitor_scans_pricing_and_jobs(self, mock_db, cfg):
        monitor = CompetitorMonitor(mock_db, cfg)
        with patch("agents.research.competitor_monitor.web_search") as mock_search, \
             patch("agents.research.competitor_monitor.llm") as mock_llm, \
             patch("agents.research.competitor_monitor.enqueue_strategy_signal"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({"changes_detected": False, "summary": "", "recommended_response": ""}))
            ]
            mock_db.get_latest_snapshot.return_value = None
            monitor.run(product="starpio")
        assert mock_search.call_count >= 3


# ---------------------------------------------------------------------------
# MarketSignalScan
# ---------------------------------------------------------------------------

class TestMarketSignalScan:

    def test_scan_searches_per_keyword(self, mock_db, cfg):
        scanner = MarketSignalScan(mock_db, cfg)
        with patch("agents.research.market_signal_scan.web_search") as mock_search, \
             patch("agents.research.market_signal_scan.llm") as mock_llm, \
             patch("agents.research.market_signal_scan.enqueue_reporting_signal"):
            mock_search.return_value = [
                {"title": "Google updates review policy", "url": "https://example.com/1", "snippet": "Details..."}
            ]
            mock_llm.complete.return_value.content = [MagicMock(text="8")]
            result = scanner.run(product="starpio")
        # 3 keywords for starpio
        assert mock_search.call_count == 3

    def test_scan_saves_high_relevance_signals(self, mock_db, cfg):
        scanner = MarketSignalScan(mock_db, cfg)
        with patch("agents.research.market_signal_scan.web_search") as mock_search, \
             patch("agents.research.market_signal_scan.llm") as mock_llm, \
             patch("agents.research.market_signal_scan.enqueue_reporting_signal"):
            mock_search.return_value = [
                {"title": "Review automation trend", "url": "https://ex.com", "snippet": "Growing fast"}
            ]
            mock_llm.complete.return_value.content = [MagicMock(text="9")]
            result = scanner.run(product="starpio")
        assert mock_db.save_signal.call_count >= 1
        assert result["signals_saved"] >= 1

    def test_scan_skips_low_relevance_signals(self, mock_db, cfg):
        scanner = MarketSignalScan(mock_db, cfg)
        with patch("agents.research.market_signal_scan.web_search") as mock_search, \
             patch("agents.research.market_signal_scan.llm") as mock_llm, \
             patch("agents.research.market_signal_scan.enqueue_reporting_signal"):
            mock_search.return_value = [
                {"title": "Unrelated tech news", "url": "https://ex.com", "snippet": "Nothing relevant"}
            ]
            mock_llm.complete.return_value.content = [MagicMock(text="3")]
            result = scanner.run(product="starpio")
        mock_db.save_signal.assert_not_called()
        assert result["signals_saved"] == 0

    def test_scan_queues_high_signals_to_reporting(self, mock_db, cfg):
        scanner = MarketSignalScan(mock_db, cfg)
        with patch("agents.research.market_signal_scan.web_search") as mock_search, \
             patch("agents.research.market_signal_scan.llm") as mock_llm, \
             patch("agents.research.market_signal_scan.enqueue_reporting_signal") as mock_enqueue:
            mock_search.return_value = [
                {"title": "Big review management shift", "url": "https://ex.com", "snippet": "Trend story"}
            ]
            mock_llm.complete.return_value.content = [MagicMock(text="8")]
            scanner.run(product="starpio")
        assert mock_enqueue.call_count >= 1

    def test_scan_threshold_exactly_7_is_high(self, mock_db, cfg):
        scanner = MarketSignalScan(mock_db, cfg)
        with patch("agents.research.market_signal_scan.web_search") as mock_search, \
             patch("agents.research.market_signal_scan.llm") as mock_llm, \
             patch("agents.research.market_signal_scan.enqueue_reporting_signal") as mock_enqueue:
            mock_search.return_value = [
                {"title": "Borderline relevant story", "url": "https://ex.com", "snippet": "Somewhat related"}
            ]
            mock_llm.complete.return_value.content = [MagicMock(text="7")]
            result = scanner.run(product="starpio")
        assert result["signals_saved"] >= 1
        assert mock_enqueue.call_count >= 1

    def test_scan_result_has_required_keys(self, mock_db, cfg):
        scanner = MarketSignalScan(mock_db, cfg)
        with patch("agents.research.market_signal_scan.web_search") as mock_search, \
             patch("agents.research.market_signal_scan.llm") as mock_llm, \
             patch("agents.research.market_signal_scan.enqueue_reporting_signal"):
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [MagicMock(text="2")]
            result = scanner.run(product="starpio")
        for key in ("product", "keywords_scanned", "signals_saved", "signals_queued"):
            assert key in result


# ---------------------------------------------------------------------------
# CustomerSentiment
# ---------------------------------------------------------------------------

class TestCustomerSentiment:

    def test_sentiment_calls_llm_with_all_sources(self, mock_db, cfg):
        sentiment = CustomerSentiment(mock_db, cfg)
        with patch("agents.research.customer_sentiment.llm") as mock_llm, \
             patch("agents.research.customer_sentiment.enqueue_strategy_signal"), \
             patch("agents.research.customer_sentiment.db_save_sentiment_report"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "pain_points": ["slow load times", "no Yelp integration"],
                    "desired_features": ["bulk responses", "Yelp support"],
                    "customer_phrases": ["set it and forget it", "saves me hours"],
                    "overall_sentiment": "positive",
                }))
            ]
            result = sentiment.run(product="starpio")
        mock_llm.complete.assert_called_once()
        call_args = mock_llm.complete.call_args
        prompt_text = str(call_args)
        assert "tickets" in prompt_text or "nps" in prompt_text or "review" in prompt_text

    def test_sentiment_extracts_pain_points(self, mock_db, cfg):
        sentiment = CustomerSentiment(mock_db, cfg)
        with patch("agents.research.customer_sentiment.llm") as mock_llm, \
             patch("agents.research.customer_sentiment.enqueue_strategy_signal"), \
             patch("agents.research.customer_sentiment.db_save_sentiment_report"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "pain_points": ["no Yelp integration", "slow mobile app"],
                    "desired_features": ["Yelp support"],
                    "customer_phrases": ["saves me hours"],
                    "overall_sentiment": "mixed",
                }))
            ]
            result = sentiment.run(product="starpio")
        assert "pain_points" in result
        assert len(result["pain_points"]) == 2

    def test_sentiment_extracts_customer_phrases(self, mock_db, cfg):
        sentiment = CustomerSentiment(mock_db, cfg)
        with patch("agents.research.customer_sentiment.llm") as mock_llm, \
             patch("agents.research.customer_sentiment.enqueue_strategy_signal"), \
             patch("agents.research.customer_sentiment.db_save_sentiment_report"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "pain_points": [],
                    "desired_features": [],
                    "customer_phrases": ["set it and forget it", "autopilot for reviews"],
                    "overall_sentiment": "positive",
                }))
            ]
            result = sentiment.run(product="starpio")
        assert "customer_phrases" in result
        assert "set it and forget it" in result["customer_phrases"]

    def test_sentiment_top_insights_go_to_strategy(self, mock_db, cfg):
        sentiment = CustomerSentiment(mock_db, cfg)
        with patch("agents.research.customer_sentiment.llm") as mock_llm, \
             patch("agents.research.customer_sentiment.enqueue_strategy_signal") as mock_signal, \
             patch("agents.research.customer_sentiment.db_save_sentiment_report"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "pain_points": ["no Yelp integration"],
                    "desired_features": ["Yelp support"],
                    "customer_phrases": ["autopilot"],
                    "overall_sentiment": "positive",
                }))
            ]
            sentiment.run(product="starpio")
        mock_signal.assert_called_once()

    def test_sentiment_saves_report_to_db(self, mock_db, cfg):
        sentiment = CustomerSentiment(mock_db, cfg)
        with patch("agents.research.customer_sentiment.llm") as mock_llm, \
             patch("agents.research.customer_sentiment.enqueue_strategy_signal"), \
             patch("agents.research.customer_sentiment.db_save_sentiment_report") as mock_save:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "pain_points": [],
                    "desired_features": [],
                    "customer_phrases": [],
                    "overall_sentiment": "neutral",
                }))
            ]
            sentiment.run(product="starpio")
        mock_save.assert_called_once()

    def test_sentiment_result_has_required_keys(self, mock_db, cfg):
        sentiment = CustomerSentiment(mock_db, cfg)
        with patch("agents.research.customer_sentiment.llm") as mock_llm, \
             patch("agents.research.customer_sentiment.enqueue_strategy_signal"), \
             patch("agents.research.customer_sentiment.db_save_sentiment_report"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "pain_points": [],
                    "desired_features": [],
                    "customer_phrases": [],
                    "overall_sentiment": "neutral",
                }))
            ]
            result = sentiment.run(product="starpio")
        for key in ("product", "pain_points", "desired_features", "customer_phrases", "overall_sentiment"):
            assert key in result


# ---------------------------------------------------------------------------
# FeatureGapAnalysis
# ---------------------------------------------------------------------------

class TestFeatureGapAnalysis:

    def test_gap_analysis_searches_competitor_features(self, mock_db, cfg):
        analysis = FeatureGapAnalysis(mock_db, cfg)
        with patch("agents.research.feature_gap_analysis.web_search") as mock_search, \
             patch("agents.research.feature_gap_analysis.llm") as mock_llm, \
             patch("agents.research.feature_gap_analysis.enqueue_dev_proposal"):
            mock_search.return_value = [{"title": "BirdEye features", "snippet": "bulk responses, Yelp, SMS"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"feature": "bulk_response", "competitor_coverage": 3, "customer_demand_score": 8, "effort": "medium"},
                    {"feature": "yelp_integration", "competitor_coverage": 2, "customer_demand_score": 9, "effort": "high"},
                    {"feature": "sms_review_request", "competitor_coverage": 3, "customer_demand_score": 6, "effort": "low"},
                ]))
            ]
            result = analysis.run(product="starpio")
        assert mock_search.call_count >= len(cfg["products"]["starpio"]["competitors"])

    def test_gap_analysis_saves_gaps_to_db(self, mock_db, cfg):
        analysis = FeatureGapAnalysis(mock_db, cfg)
        with patch("agents.research.feature_gap_analysis.web_search") as mock_search, \
             patch("agents.research.feature_gap_analysis.llm") as mock_llm, \
             patch("agents.research.feature_gap_analysis.enqueue_dev_proposal"):
            mock_search.return_value = [{"title": "features", "snippet": "bulk, yelp"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"feature": "bulk_response", "competitor_coverage": 3, "customer_demand_score": 8, "effort": "medium"},
                    {"feature": "yelp_integration", "competitor_coverage": 2, "customer_demand_score": 9, "effort": "high"},
                ]))
            ]
            analysis.run(product="starpio")
        assert mock_db.save_feature_gap.call_count == 2

    def test_gap_analysis_enqueues_top_3_to_dev(self, mock_db, cfg):
        analysis = FeatureGapAnalysis(mock_db, cfg)
        with patch("agents.research.feature_gap_analysis.web_search") as mock_search, \
             patch("agents.research.feature_gap_analysis.llm") as mock_llm, \
             patch("agents.research.feature_gap_analysis.enqueue_dev_proposal") as mock_dev:
            mock_search.return_value = [{"title": "features", "snippet": "many features"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"feature": "bulk_response", "competitor_coverage": 3, "customer_demand_score": 9, "effort": "low"},
                    {"feature": "yelp_integration", "competitor_coverage": 3, "customer_demand_score": 8, "effort": "medium"},
                    {"feature": "facebook_reviews", "competitor_coverage": 2, "customer_demand_score": 7, "effort": "medium"},
                    {"feature": "sms_blasts", "competitor_coverage": 1, "customer_demand_score": 5, "effort": "high"},
                ]))
            ]
            analysis.run(product="starpio")
        assert mock_dev.call_count == 3

    def test_gap_analysis_enqueues_fewer_when_less_than_3_gaps(self, mock_db, cfg):
        analysis = FeatureGapAnalysis(mock_db, cfg)
        with patch("agents.research.feature_gap_analysis.web_search") as mock_search, \
             patch("agents.research.feature_gap_analysis.llm") as mock_llm, \
             patch("agents.research.feature_gap_analysis.enqueue_dev_proposal") as mock_dev:
            mock_search.return_value = [{"title": "features", "snippet": "one feature"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"feature": "yelp_integration", "competitor_coverage": 1, "customer_demand_score": 8, "effort": "high"},
                ]))
            ]
            analysis.run(product="starpio")
        assert mock_dev.call_count == 1

    def test_gap_analysis_result_has_required_keys(self, mock_db, cfg):
        analysis = FeatureGapAnalysis(mock_db, cfg)
        with patch("agents.research.feature_gap_analysis.web_search") as mock_search, \
             patch("agents.research.feature_gap_analysis.llm") as mock_llm, \
             patch("agents.research.feature_gap_analysis.enqueue_dev_proposal"):
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [MagicMock(text="[]")]
            result = analysis.run(product="starpio")
        for key in ("product", "gaps_found", "gaps_proposed_to_dev", "gaps"):
            assert key in result

    def test_gap_analysis_excludes_existing_features(self, mock_db, cfg):
        analysis = FeatureGapAnalysis(mock_db, cfg)
        with patch("agents.research.feature_gap_analysis.web_search") as mock_search, \
             patch("agents.research.feature_gap_analysis.llm") as mock_llm, \
             patch("agents.research.feature_gap_analysis.enqueue_dev_proposal"):
            mock_search.return_value = [{"title": "features", "snippet": "ai responses, bulk"}]
            # LLM returns a mix — ai_responses is already in feature_set
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"feature": "ai_responses", "competitor_coverage": 3, "customer_demand_score": 9, "effort": "low"},
                    {"feature": "bulk_response", "competitor_coverage": 2, "customer_demand_score": 8, "effort": "medium"},
                ]))
            ]
            result = analysis.run(product="starpio")
        # ai_responses already exists — should be filtered out
        gap_features = [g["feature"] for g in result["gaps"]]
        assert "ai_responses" not in gap_features


# ---------------------------------------------------------------------------
# PricingResearch
# ---------------------------------------------------------------------------

class TestPricingResearch:

    def test_pricing_research_scrapes_all_competitors(self, mock_db, cfg):
        research = PricingResearch(mock_db, cfg)
        with patch("agents.research.pricing_research.web_search") as mock_search, \
             patch("agents.research.pricing_research.llm") as mock_llm, \
             patch("agents.research.pricing_research.enqueue_strategy_report"):
            mock_search.return_value = [{"title": "BirdEye pricing", "snippet": "$299/mo starter"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "competitor_pricing": {
                        "birdeye": {"starter": 299, "pro": 499, "enterprise": "custom"},
                        "podium": {"starter": 289, "pro": 449, "enterprise": "custom"},
                        "grade_us": {"starter": 99, "pro": 199, "enterprise": 399},
                    },
                    "recommendation": "Price at $149/mo starter — undercut birdeye/podium while staying above grade_us",
                    "rationale": "Strong value position with AI differentiator",
                }))
            ]
            result = research.run(product="starpio")
        assert mock_search.call_count >= len(cfg["products"]["starpio"]["competitors"])

    def test_pricing_research_does_not_change_pricing(self, mock_db, cfg):
        research = PricingResearch(mock_db, cfg)
        with patch("agents.research.pricing_research.web_search") as mock_search, \
             patch("agents.research.pricing_research.llm") as mock_llm, \
             patch("agents.research.pricing_research.enqueue_strategy_report") as mock_report:
            mock_search.return_value = [{"title": "Pricing", "snippet": "$299/mo"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "competitor_pricing": {},
                    "recommendation": "Keep current pricing",
                    "rationale": "Competitive",
                }))
            ]
            result = research.run(product="starpio")
        # Should enqueue report, NOT directly modify anything in the product
        mock_report.assert_called_once()
        assert result.get("pricing_changed") is None

    def test_pricing_research_delivers_report_to_strategy(self, mock_db, cfg):
        research = PricingResearch(mock_db, cfg)
        with patch("agents.research.pricing_research.web_search") as mock_search, \
             patch("agents.research.pricing_research.llm") as mock_llm, \
             patch("agents.research.pricing_research.enqueue_strategy_report") as mock_report:
            mock_search.return_value = [{"title": "Pricing info", "snippet": "$199/mo"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "competitor_pricing": {"birdeye": {"starter": 299}},
                    "recommendation": "Reduce starter to $149",
                    "rationale": "Better conversion expected",
                }))
            ]
            research.run(product="starpio")
        mock_report.assert_called_once()
        report_kwargs = mock_report.call_args.kwargs
        assert report_kwargs["product"] == "starpio"
        assert "recommendation" in report_kwargs

    def test_pricing_research_result_has_required_keys(self, mock_db, cfg):
        research = PricingResearch(mock_db, cfg)
        with patch("agents.research.pricing_research.web_search") as mock_search, \
             patch("agents.research.pricing_research.llm") as mock_llm, \
             patch("agents.research.pricing_research.enqueue_strategy_report"):
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "competitor_pricing": {},
                    "recommendation": "Maintain pricing",
                    "rationale": "Stable market",
                }))
            ]
            result = research.run(product="starpio")
        for key in ("product", "competitors_researched", "recommendation", "rationale"):
            assert key in result

    def test_pricing_research_llm_produces_recommendation(self, mock_db, cfg):
        research = PricingResearch(mock_db, cfg)
        with patch("agents.research.pricing_research.web_search") as mock_search, \
             patch("agents.research.pricing_research.llm") as mock_llm, \
             patch("agents.research.pricing_research.enqueue_strategy_report"):
            mock_search.return_value = [{"title": "Pricing", "snippet": "$299/mo"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "competitor_pricing": {"birdeye": {"starter": 299}},
                    "recommendation": "Price at $149/mo",
                    "rationale": "Undercut on value",
                }))
            ]
            result = research.run(product="starpio")
        assert result["recommendation"] == "Price at $149/mo"
        mock_llm.complete.assert_called_once()


# ---------------------------------------------------------------------------
# ResearchAgent dispatch
# ---------------------------------------------------------------------------

class TestResearchAgent:

    @pytest.fixture
    def agent(self, cfg):
        from agents.research.main import ResearchAgent
        config = MagicMock(spec=AgentConfig)
        config.custom = cfg
        config.llm_system_prompt = ""
        config.poll_interval_seconds = 2
        with patch("agents.research.main.ResearchDB"), \
             patch("agents.research.main.CompetitorMonitor"), \
             patch("agents.research.main.MarketSignalScan"), \
             patch("agents.research.main.CustomerSentiment"), \
             patch("agents.research.main.FeatureGapAnalysis"), \
             patch("agents.research.main.PricingResearch"):
            return ResearchAgent("research", config)

    def test_unknown_action_returns_error(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "hack_the_matrix"},
        )
        result = agent.handle(task)
        assert result.success is False
        assert "error" in result.output

    def test_competitor_monitor_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "competitor_monitor", "product": "starpio"},
        )
        agent._competitor_monitor.run.return_value = {
            "product": "starpio", "competitors_scanned": 3, "changes_found": 1, "snapshots": []
        }
        result = agent.handle(task)
        assert result.success is True
        agent._competitor_monitor.run.assert_called_once_with(product="starpio")

    def test_market_signal_scan_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "market_signal_scan", "product": "starpio"},
        )
        agent._signal_scan.run.return_value = {
            "product": "starpio", "keywords_scanned": 3, "signals_saved": 2, "signals_queued": 2
        }
        result = agent.handle(task)
        assert result.success is True
        agent._signal_scan.run.assert_called_once_with(product="starpio")

    def test_customer_sentiment_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "customer_sentiment", "product": "starpio"},
        )
        agent._sentiment.run.return_value = {
            "product": "starpio", "pain_points": [], "desired_features": [],
            "customer_phrases": [], "overall_sentiment": "positive",
        }
        result = agent.handle(task)
        assert result.success is True
        agent._sentiment.run.assert_called_once_with(product="starpio")

    def test_feature_gap_analysis_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "feature_gap_analysis", "product": "starpio"},
        )
        agent._gap_analysis.run.return_value = {
            "product": "starpio", "gaps_found": 3, "gaps_proposed_to_dev": 3, "gaps": []
        }
        result = agent.handle(task)
        assert result.success is True
        agent._gap_analysis.run.assert_called_once_with(product="starpio")

    def test_pricing_research_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "pricing_research", "product": "starpio"},
        )
        agent._pricing.run.return_value = {
            "product": "starpio", "competitors_researched": 3,
            "recommendation": "Keep current", "rationale": "Stable",
        }
        result = agent.handle(task)
        assert result.success is True
        agent._pricing.run.assert_called_once_with(product="starpio")

    def test_missing_product_returns_error(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "competitor_monitor"},
        )
        result = agent.handle(task)
        assert result.success is False
        assert "error" in result.output

    def test_health_check_true_when_db_ok(self, agent):
        agent._db.list_signals.return_value = []
        assert agent.health_check() is True

    def test_health_check_false_on_db_error(self, agent):
        agent._db.list_signals.side_effect = Exception("db down")
        assert agent.health_check() is False
