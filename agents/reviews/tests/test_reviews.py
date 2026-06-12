"""Reviews agent unit tests — no external services required."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agents._base import AgentConfig
from agents.reviews.db import ReviewsDB
from agents.reviews.fake_detector import FakeReviewDetector
from agents.reviews.responder import ReviewResponder
from shared.types import AgentCapability, Task, TaskResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _review(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "platform": "google",
        "external_id": str(uuid.uuid4()),
        "reviewer_name": "John D.",
        "reviewer_review_count": 42,
        "reviewer_has_photo": True,
        "rating": 5,
        "review_text": "Dutch and his crew replaced our water heater. On time, clean job.",
        "posted_at": datetime.now(timezone.utc),
        "business": "trusted_plumbing",
        "platform_ref": {
            "review_name": "accounts/123/locations/456/reviews/abc",
            "account_name": "accounts/123",
            "location_name": "locations/456",
        },
        "responded_at": None,
        "flagged": False,
        "flag_confidence": None,
    }
    if overrides:
        base.update(overrides)
    return base


def _cfg() -> dict:
    return {
        "listings": {
            "gbp": [{"business": "trusted_plumbing"}],
            "yelp": [{"business": "trusted_plumbing"}],
            "facebook": [{"business": "trusted_plumbing"}],
        },
        "alert_thresholds": {"trusted_plumbing": 4.5},
        "rolling_average_days": 30,
        "fake_review_confidence_threshold": 0.8,
        "review_request_delay_hours": 24,
        "from_email": "dutch@test.com",
        "from_name": "Dutch Munn",
        "from_password": "secret",
    }


@pytest.fixture
def mock_db():
    return MagicMock(spec=ReviewsDB)


@pytest.fixture
def cfg():
    return _cfg()


# ---------------------------------------------------------------------------
# TestFakeReviewDetector
# ---------------------------------------------------------------------------

class TestFakeReviewDetector:

    def test_clean_reviewer_scores_low(self):
        detector = FakeReviewDetector()
        review = _review({
            "reviewer_review_count": 85,
            "reviewer_has_photo": True,
            "review_text": "Dutch and his crew replaced our water heater on time. Clean job, no mess left behind.",
        })
        confidence, reasons = detector.score(review)
        assert confidence < 0.4
        assert not detector.should_flag(confidence)

    def test_zero_reviews_no_photo_short_text_scores_high(self):
        detector = FakeReviewDetector()
        review = _review({
            "reviewer_review_count": 0,
            "reviewer_has_photo": False,
            "review_text": "Great!",
        })
        confidence, reasons = detector.score(review)
        assert confidence >= 0.7
        assert "reviewer_count_low(0)" in reasons
        assert "no_profile_photo" in reasons

    def test_none_review_count_triggers_low_count_signal(self):
        detector = FakeReviewDetector()
        review = _review({
            "reviewer_review_count": None,
            "reviewer_has_photo": False,
            "review_text": "Highly recommend! Great service! Very professional!",
        })
        confidence, reasons = detector.score(review)
        assert any("reviewer_count_low" in r for r in reasons)

    def test_generic_name_adds_signal(self):
        detector = FakeReviewDetector()
        review = _review({
            "reviewer_name": "user12345678",
            "reviewer_review_count": 1,
            "reviewer_has_photo": False,
            "review_text": "Great service highly recommend",
        })
        confidence, reasons = detector.score(review)
        assert "generic_reviewer_name" in reasons

    def test_should_flag_threshold(self):
        detector = FakeReviewDetector()
        assert detector.should_flag(0.85) is True
        assert detector.should_flag(0.79) is False
        assert detector.should_flag(0.8) is True

    def test_all_signals_capped_at_1(self):
        detector = FakeReviewDetector()
        review = _review({
            "reviewer_name": "user99999",
            "reviewer_review_count": 0,
            "reviewer_has_photo": False,
            "review_text": "gr",
        })
        confidence, _ = detector.score(review)
        assert confidence <= 1.0

    def test_multiple_boilerplate_phrases_adds_score(self):
        detector = FakeReviewDetector()
        review = _review({
            "reviewer_review_count": 2,
            "reviewer_has_photo": True,
            "review_text": "Highly recommend, great service, very professional, great job, awesome!",
        })
        confidence, reasons = detector.score(review)
        assert any("generic_phrases" in r for r in reasons)


# ---------------------------------------------------------------------------
# TestReviewResponder
# ---------------------------------------------------------------------------

class TestReviewResponder:

    @patch("agents.reviews.responder.GBPReviews")
    @patch("agents.reviews.responder.YelpReviews")
    @patch("agents.reviews.responder.FacebookReviews")
    @patch("agents.reviews.responder.llm")
    def test_five_star_generates_and_posts(self, mock_llm, _fb, _yelp, mock_gbp_cls, mock_db):
        mock_db.get_review.return_value = _review({"rating": 5})
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Thanks so much, John!")]
        mock_llm.complete.return_value = mock_resp

        mock_gbp_instance = MagicMock()
        mock_gbp_cls.return_value = mock_gbp_instance
        mock_gbp_instance.reply.return_value = {"name": "reply/123"}

        responder = ReviewResponder(mock_db)
        result = responder.respond(str(uuid.uuid4()))

        assert result["outcome"] == "posted"
        mock_db.mark_responded.assert_called_once()
        mock_db.log_response.assert_called_once()

    @patch("agents.reviews.responder.GBPReviews")
    @patch("agents.reviews.responder.YelpReviews")
    @patch("agents.reviews.responder.FacebookReviews")
    @patch("agents.reviews.responder.llm")
    def test_one_star_response_uses_accountability_tone(self, mock_llm, _fb, _yelp, _gbp, mock_db):
        mock_db.get_review.return_value = _review({"rating": 1, "review_text": "Showed up late and flooded my basement."})
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="I'm sorry about that.")]
        mock_llm.complete.return_value = mock_resp

        responder = ReviewResponder(mock_db)
        call_args = None

        def capture(*args, **kwargs):
            nonlocal call_args
            call_args = kwargs.get("system") or args[1] if args else kwargs.get("system")
            return mock_resp

        mock_llm.complete.side_effect = capture
        responder.respond(str(uuid.uuid4()))

        # Verify the LLM was called with the accountability system prompt
        assert mock_llm.complete.called

    @patch("agents.reviews.responder.GBPReviews")
    @patch("agents.reviews.responder.YelpReviews")
    @patch("agents.reviews.responder.FacebookReviews")
    @patch("agents.reviews.responder.llm")
    def test_already_responded_is_skipped(self, mock_llm, _fb, _yelp, _gbp, mock_db):
        mock_db.get_review.return_value = _review({"responded_at": datetime.now(timezone.utc)})
        responder = ReviewResponder(mock_db)
        result = responder.respond(str(uuid.uuid4()))
        assert result["skipped"] is True
        mock_llm.complete.assert_not_called()

    @patch("agents.reviews.responder.GBPReviews")
    @patch("agents.reviews.responder.YelpReviews")
    @patch("agents.reviews.responder.FacebookReviews")
    @patch("agents.reviews.responder.llm")
    def test_yelp_review_marked_manual_post_required(self, mock_llm, _fb, mock_yelp_cls, _gbp, mock_db):
        mock_db.get_review.return_value = _review({
            "platform": "yelp",
            "platform_ref": {"yelp_review_id": "abc", "yelp_url": "https://yelp.com/..."},
        })
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Thanks!")]
        mock_llm.complete.return_value = mock_resp

        mock_yelp_instance = MagicMock()
        mock_yelp_cls.return_value = mock_yelp_instance
        mock_yelp_instance.reply.return_value = {"outcome": "manual_post_required"}

        responder = ReviewResponder(mock_db)
        result = responder.respond(str(uuid.uuid4()))
        assert result["outcome"] == "manual_post_required"
        mock_db.mark_responded.assert_called_once()

    @patch("agents.reviews.responder.GBPReviews")
    @patch("agents.reviews.responder.YelpReviews")
    @patch("agents.reviews.responder.FacebookReviews")
    def test_review_not_found_returns_error(self, _fb, _yelp, _gbp, mock_db):
        mock_db.get_review.return_value = None
        responder = ReviewResponder(mock_db)
        result = responder.respond("nonexistent-id")
        assert result["error"] == "review_not_found"


# ---------------------------------------------------------------------------
# TestReviewsAgentDispatch
# ---------------------------------------------------------------------------

class TestReviewsAgentDispatch:

    def _make_agent(self):
        from agents.reviews.main import ReviewsAgent

        config = AgentConfig(agent_name="reviews", custom=_cfg())
        return ReviewsAgent("reviews", config)

    def _task(self, payload: dict) -> Task:
        return Task(id=str(uuid.uuid4()), agent=AgentCapability.REVIEWS, payload=payload)

    @patch("agents.reviews.main.ReviewsDB")
    @patch("agents.reviews.main.ReviewResponder")
    @patch("agents.reviews.main.ReviewRequestSender")
    def test_unknown_action_raises(self, _rs, _rr, _db):
        agent = self._make_agent()
        with pytest.raises(ValueError, match="Unknown reviews action"):
            agent.handle(self._task({"action": "does_not_exist"}))

    @patch("agents.reviews.main.ReviewsDB")
    @patch("agents.reviews.main.ReviewResponder")
    @patch("agents.reviews.main.ReviewRequestSender")
    def test_respond_to_review_missing_review_id(self, _rs, _rr, _db):
        agent = self._make_agent()
        result = agent.handle(self._task({"action": "respond_to_review"}))
        assert result.output["error"] == "review_id required"

    @patch("agents.reviews.main.ReviewsDB")
    @patch("agents.reviews.main.ReviewResponder")
    @patch("agents.reviews.main.ReviewRequestSender")
    def test_review_request_missing_job_id(self, _rs, _rr, _db):
        agent = self._make_agent()
        result = agent.handle(self._task({"action": "review_request"}))
        assert result.output["error"] == "job_id required"

    @patch("agents.reviews.main.ReviewsDB")
    @patch("agents.reviews.main.ReviewResponder")
    @patch("agents.reviews.main.ReviewRequestSender")
    def test_monitor_platform_error_does_not_crash(self, _rs, _rr, mock_db_cls):
        agent = self._make_agent()
        agent._gbp = MagicMock()
        agent._gbp.poll.side_effect = Exception("GBP credential missing")
        agent._yelp = MagicMock()
        agent._yelp.poll.return_value = []
        agent._fb = MagicMock()
        agent._fb.poll.return_value = []
        agent._db.review_exists.return_value = False

        result = agent.handle(self._task({"action": "monitor_reviews"}))
        assert result.success is True
        assert result.output["new_reviews_found"] == 0
        assert len(result.output["errors"]) == 1

    @patch("agents.reviews.main.ReviewsDB")
    @patch("agents.reviews.main.ReviewResponder")
    @patch("agents.reviews.main.ReviewRequestSender")
    def test_monitor_ingests_new_review_and_enqueues_tasks(self, _rs, _rr, mock_db_cls):
        agent = self._make_agent()
        agent._db.review_exists.return_value = False
        agent._db.upsert_review.return_value = "review-uuid-123"
        agent._queue = MagicMock()

        fake_review = {
            "platform": "google",
            "external_id": "ext-123",
            "reviewer_name": "Jane",
            "rating": 4,
            "review_text": "Really good work.",
            "posted_at": datetime.now(timezone.utc),
            "business": "trusted_plumbing",
            "platform_ref": {},
            "reviewer_review_count": 10,
            "reviewer_has_photo": True,
            "already_replied": False,
        }
        agent._gbp = MagicMock()
        agent._gbp.poll.return_value = [fake_review]
        agent._yelp = MagicMock()
        agent._yelp.poll.return_value = []
        agent._fb = MagicMock()
        agent._fb.poll.return_value = []

        result = agent.handle(self._task({"action": "monitor_reviews"}))
        assert result.output["new_reviews_found"] == 1
        # respond + flag tasks enqueued
        assert agent._queue.push.call_count == 2

    @patch("agents.reviews.main.ReviewsDB")
    @patch("agents.reviews.main.ReviewResponder")
    @patch("agents.reviews.main.ReviewRequestSender")
    def test_monitor_skips_already_seen_review(self, _rs, _rr, mock_db_cls):
        agent = self._make_agent()
        agent._db.review_exists.return_value = True
        agent._queue = MagicMock()
        agent._gbp = MagicMock()
        agent._gbp.poll.return_value = [{
            "platform": "google",
            "external_id": "seen-id",
            "reviewer_name": "Bob",
            "rating": 5,
            "review_text": "Great!",
            "posted_at": datetime.now(timezone.utc),
            "business": "trusted_plumbing",
            "platform_ref": {},
            "already_replied": False,
        }]
        agent._yelp = MagicMock()
        agent._yelp.poll.return_value = []
        agent._fb = MagicMock()
        agent._fb.poll.return_value = []

        result = agent.handle(self._task({"action": "monitor_reviews"}))
        assert result.output["new_reviews_found"] == 0
        agent._queue.push.assert_not_called()

    @patch("agents.reviews.main.ReviewsDB")
    @patch("agents.reviews.main.ReviewResponder")
    @patch("agents.reviews.main.ReviewRequestSender")
    @patch("agents.reviews.main.SlackConnector")
    def test_reputation_alert_below_threshold_alerts_slack(self, mock_slack_cls, _rs, _rr, mock_db_cls):
        agent = self._make_agent()
        agent._db.rolling_average.return_value = 4.1  # below 4.5 threshold
        agent._db.recent_review_count.return_value = 15
        agent._queue = MagicMock()

        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        result = agent.handle(self._task({
            "action": "reputation_alert",
            "business": "trusted_plumbing",
        }))

        assert result.output["alerts_sent"] == 1
        mock_slack.send_message.assert_called_once()
        agent._queue.push.assert_called_once()

    @patch("agents.reviews.main.ReviewsDB")
    @patch("agents.reviews.main.ReviewResponder")
    @patch("agents.reviews.main.ReviewRequestSender")
    def test_reputation_alert_above_threshold_no_alert(self, _rs, _rr, mock_db_cls):
        agent = self._make_agent()
        agent._db.rolling_average.return_value = 4.8  # above 4.5 threshold
        agent._db.recent_review_count.return_value = 20
        agent._queue = MagicMock()

        result = agent.handle(self._task({
            "action": "reputation_alert",
            "business": "trusted_plumbing",
        }))
        assert result.output["alerts_sent"] == 0
        agent._queue.push.assert_not_called()

    @patch("agents.reviews.main.ReviewsDB")
    @patch("agents.reviews.main.ReviewResponder")
    @patch("agents.reviews.main.ReviewRequestSender")
    def test_reputation_alert_skipped_if_too_few_reviews(self, _rs, _rr, mock_db_cls):
        agent = self._make_agent()
        agent._db.rolling_average.return_value = 3.0
        agent._db.recent_review_count.return_value = 3  # < 5 minimum
        agent._queue = MagicMock()

        result = agent.handle(self._task({
            "action": "reputation_alert",
            "business": "trusted_plumbing",
        }))
        assert result.output["alerts_sent"] == 0


# ---------------------------------------------------------------------------
# TestReviewsAgentFlagFake
# ---------------------------------------------------------------------------

class TestReviewsAgentFlagFake:

    def _make_agent(self):
        from agents.reviews.main import ReviewsAgent

        config = AgentConfig(agent_name="reviews", custom=_cfg())
        return ReviewsAgent("reviews", config)

    def _task(self, payload: dict) -> Task:
        return Task(id=str(uuid.uuid4()), agent=AgentCapability.REVIEWS, payload=payload)

    @patch("agents.reviews.main.ReviewsDB")
    @patch("agents.reviews.main.ReviewResponder")
    @patch("agents.reviews.main.ReviewRequestSender")
    def test_high_confidence_review_gets_flagged(self, _rs, _rr, mock_db_cls):
        agent = self._make_agent()
        # 0.35 (count=0) + 0.20 (no photo) + 0.15 (short text) + 0.10 (generic name) = 0.80 → auto-flag
        suspicious = _review({
            "reviewer_name": "user99887766",
            "reviewer_review_count": 0,
            "reviewer_has_photo": False,
            "review_text": "gr",
        })
        agent._db.get_review.return_value = suspicious

        result = agent.handle(self._task({
            "action": "flag_fake_review",
            "review_id": suspicious["id"],
        }))
        assert result.output["reviews_scanned"] == 1
        assert result.output["auto_flagged"] == 1
        agent._db.flag_review.assert_called_once()

    @patch("agents.reviews.main.ReviewsDB")
    @patch("agents.reviews.main.ReviewResponder")
    @patch("agents.reviews.main.ReviewRequestSender")
    def test_clean_review_not_flagged(self, _rs, _rr, mock_db_cls):
        agent = self._make_agent()
        clean = _review({
            "reviewer_review_count": 75,
            "reviewer_has_photo": True,
            "review_text": "Dutch replaced our main water shutoff and fixed a stubborn leak under the sink.",
        })
        agent._db.get_review.return_value = clean

        result = agent.handle(self._task({
            "action": "flag_fake_review",
            "review_id": clean["id"],
        }))
        assert result.output["auto_flagged"] == 0
        agent._db.flag_review.assert_not_called()


# ---------------------------------------------------------------------------
# TestReviewsDB (unit — no real DB)
# ---------------------------------------------------------------------------

class TestReviewsDB:

    def test_review_request_sent_returns_false_when_no_record(self):
        db = ReviewsDB.__new__(ReviewsDB)
        with patch("agents.reviews.db.get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = None
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = db.review_request_sent("job-xyz", "trusted_plumbing")
        assert result is False

    def test_review_exists_returns_false_when_no_record(self):
        db = ReviewsDB.__new__(ReviewsDB)
        with patch("agents.reviews.db.get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = None
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = db.review_exists("google", "some-external-id")
        assert result is False

    def test_rolling_average_returns_none_when_no_reviews(self):
        db = ReviewsDB.__new__(ReviewsDB)
        with patch("agents.reviews.db.get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = (None,)
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = db.rolling_average("trusted_plumbing", 30)
        assert result is None
