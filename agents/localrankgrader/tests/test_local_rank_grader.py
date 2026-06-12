"""Tests for LocalRankGrader agent — scoring, DB ops, audit dispatch."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agents._base.config import AgentConfig
from agents.localrankgrader.auditor import GBPAuditor
from agents.localrankgrader.main import LocalRankGraderAgent
from shared.types import Task, TaskResult, AgentCapability


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(action: str, payload: dict[str, Any] | None = None) -> Task:
    return Task(
        id="test-001",
        agent=AgentCapability.LOCAL_RANK_GRADER,
        payload={"action": action, **(payload or {})},
        created_at=datetime.utcnow(),
    )


@pytest.fixture()
def agent(mocker):
    config = AgentConfig(agent_name="local_rank_grader")
    a = LocalRankGraderAgent("local_rank_grader", config)
    a._redis = MagicMock()
    mocker.patch.object(a._queue, "ack")
    mocker.patch.object(a._queue, "nack")
    return a


# ---------------------------------------------------------------------------
# Scoring unit tests
# ---------------------------------------------------------------------------

class TestGBPAuditorScoring:
    def setup_method(self):
        self.auditor = GBPAuditor(
            score_weights={
                "completeness": 25, "photos": 15, "reviews": 25, "posts": 10,
                "qa": 5, "services": 5, "keywords": 10, "citations": 5,
            },
            citation_directories=["yelp.com", "yellowpages.com"],
        )

    def test_full_profile_scores_max_completeness(self):
        places = {
            "name": "Test Biz",
            "formatted_address": "123 Main St",
            "formatted_phone_number": "(555) 555-1234",
            "website": "https://test.com",
            "opening_hours": {"weekday_text": ["Mon: 9am-5pm"]},
            "editorial_summary": {"overview": "Great local business"},
        }
        scores, raw = self.auditor._calculate_scores(places, {}, {"consistent": 0, "total_checked": 0}, None)
        assert scores["completeness"] == 25

    def test_no_photos_scores_zero(self):
        places: dict[str, Any] = {"photos": []}
        scores, raw = self.auditor._calculate_scores(places, {}, {}, None)
        assert scores["photos"] == 0

    def test_16_photos_scores_max(self):
        places = {"photos": [{}] * 16}
        scores, raw = self.auditor._calculate_scores(places, {}, {}, None)
        assert scores["photos"] == 15

    def test_review_count_100_plus_gives_15(self):
        places = {"user_ratings_total": 150, "rating": 4.8}
        scores, raw = self.auditor._calculate_scores(places, {}, {}, None)
        assert raw["reviews"]["count"] == 150

    def test_keyword_in_name_gives_4_points(self):
        places = {"name": "Best plumber NYC", "types": []}
        scores, raw = self.auditor._calculate_scores(places, {}, {}, "plumber")
        assert scores["keywords"] >= 4

    def test_keyword_in_all_gives_10(self):
        places = {
            "name": "plumber pros",
            "editorial_summary": {"overview": "The best plumber in town"},
            "types": ["plumber", "contractor"],
        }
        scores, raw = self.auditor._calculate_scores(places, {}, {}, "plumber")
        assert scores["keywords"] == 10

    def test_post_within_7_days_scores_10(self):
        scores, raw = self.auditor._calculate_scores(
            {}, {"last_post_days_ago": 3}, {}, None
        )
        assert scores["posts"] == 10

    def test_post_older_than_90_days_scores_0(self):
        scores, raw = self.auditor._calculate_scores(
            {}, {"last_post_days_ago": 100}, {}, None
        )
        assert scores["posts"] == 0

    def test_7_consistent_citations_scores_5(self):
        scores, raw = self.auditor._calculate_scores(
            {}, {}, {"consistent": 7, "total_checked": 10}, None
        )
        assert scores["citations"] == 5

    def test_overall_score_capped_at_100(self):
        places = {
            "name": "The best plumber in town",
            "formatted_address": "123 Main",
            "formatted_phone_number": "555-1234",
            "website": "https://a.com",
            "opening_hours": {},
            "editorial_summary": {"overview": "We are plumbers"},
            "photos": [{}] * 20,
            "user_ratings_total": 200,
            "rating": 4.9,
            "reviews": [{"author_name": "x", "text": "great"}],
            "types": ["plumber"],
        }
        pw = {"last_post_days_ago": 1, "posts_count": 5, "qa_count": 3, "qa_answered": 3, "services_listed": True}
        nap = {"consistent": 10, "total_checked": 10}
        scores, raw = self.auditor._calculate_scores(places, pw, nap, "plumber")
        total = sum(scores.values())
        assert total <= 100

    def test_relative_days_parser(self):
        assert self.auditor._parse_relative_days("Posted 3 days ago") == 3
        assert self.auditor._parse_relative_days("2 weeks ago") == 14
        assert self.auditor._parse_relative_days("1 month ago") == 30
        assert self.auditor._parse_relative_days("updated recently") is None


# ---------------------------------------------------------------------------
# Agent dispatch
# ---------------------------------------------------------------------------

class TestLocalRankGraderAgentDispatch:
    def test_unknown_action_raises(self, agent):
        task = _make_task("nonexistent_action")
        with pytest.raises(ValueError, match="Unknown"):
            agent.handle(task)

    def test_grader_analytics_dispatches(self, agent, mocker):
        mock_summary = mocker.patch.object(agent._analytics, "daily_summary", return_value={"audits_run": 5})
        mocker.patch.object(agent._analytics, "weekly_industry_report", return_value={})

        result = agent.handle(_make_task("grader_analytics"))
        assert result.success is True
        mock_summary.assert_called_once()

    def test_auto_publish_dispatches(self, agent, mocker):
        mocker.patch.object(agent._publisher, "publish_monthly", return_value={"pages_generated": 3})
        result = agent.handle(_make_task("auto_publish_result"))
        assert result.success is True
        assert result.output["pages_generated"] == 3

    def test_run_audit_calls_all_components(self, agent, mocker):
        mocker.patch.object(agent._auditor, "audit", return_value={
            "place_id": "ChIJ123",
            "address": "100 Main St, Austin, TX",
            "overall_score": 62,
            "category_scores": {"completeness": 20, "photos": 5, "reviews": 15, "posts": 0, "qa": 0, "services": 0, "keywords": 5, "citations": 3},
            "recommendations": [{"category": "photos", "priority": "HIGH", "action": "Add more photos"}],
            "raw_places_data": {"name": "Test Co", "types": ["restaurant"]},
            "playwright_data": {},
        })
        mocker.patch.object(agent._db, "insert_audit", return_value="audit-uuid-123")
        mocker.patch.object(agent._benchmarker, "benchmark", return_value=[])
        mocker.patch.object(agent._db, "create_lead", return_value="lead-uuid-456")
        mocker.patch.object(agent._reporter, "deliver", return_value={"report_url": "https://b2.example.com/r.pdf", "score": 62})
        mocker.patch.object(agent._nurture, "schedule_sequence")

        task = _make_task("run_audit", {
            "business_name": "Test Co",
            "contact_email": "owner@test.com",
            "contact_name": "Alice",
        })
        result = agent.handle(task)

        assert result.success is True
        assert result.output["overall_score"] == 62
        assert result.output["audit_id"] == "audit-uuid-123"
        agent._nurture.schedule_sequence.assert_called_once()
        agent._reporter.deliver.assert_called_once()
