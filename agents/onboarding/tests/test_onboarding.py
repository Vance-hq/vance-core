"""Onboarding agent unit tests — no external services required."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from agents._base import AgentConfig
from agents.onboarding.db import OnboardingDB
from agents.onboarding.signup_flow import SignupFlow
from agents.onboarding.activation_nudge import ActivationNudge
from agents.onboarding.first_value import FirstValueMoment
from agents.onboarding.stuck_user import StuckUserAlert
from agents.onboarding.audit import OnboardingAudit
from shared.types import AgentCapability, Task, TaskResult


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _state(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "user_id": "user_abc",
        "product": "starpio",
        "current_milestone": "connected_gbp",
        "milestones_completed": [],
        "last_nudge_at": None,
    }
    if overrides:
        base.update(overrides)
    return base


def _event(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "user_id": "user_abc",
        "product": "starpio",
        "milestone": "connected_gbp",
        "achieved_at": datetime.now(timezone.utc),
        "days_since_signup": 0,
    }
    if overrides:
        base.update(overrides)
    return base


@pytest.fixture
def mock_db():
    db = MagicMock(spec=OnboardingDB)
    db.upsert_state.return_value = str(uuid.uuid4())
    db.get_state.return_value = _state()
    db.record_milestone.return_value = str(uuid.uuid4())
    db.get_stuck_users.return_value = []
    db.get_funnel_metrics.return_value = {
        "signup_to_activated_pct": 42.0,
        "avg_days_to_first_value": 3.1,
        "milestones": {
            "connected_gbp": {"reached": 80, "dropped": 20},
            "first_review_seen": {"reached": 55, "dropped": 25},
            "first_response_sent": {"reached": 40, "dropped": 15},
        },
    }
    db.list_milestone_times.return_value = [_event()]
    return db


@pytest.fixture
def cfg() -> dict:
    return {
        "resend_api_key": "re_test_key",
        "dutch_email": "dutch@vance.com",
        "dutch_reply_to": "dutch@vance.com",
        "supabase_url": "https://proj.supabase.co",
        "supabase_service_key": "service_key_abc",
        "products": {
            "starpio": {
                "name": "Starpio",
                "from_email": "dutch@starpio.com",
                "from_name": "Dutch",
                "milestones": ["connected_gbp", "first_review_seen", "first_response_sent"],
            },
            "oneserv": {
                "name": "Oneserv",
                "from_email": "dutch@oneserv.com",
                "from_name": "Dutch",
                "milestones": [
                    "created_account", "first_job", "first_dispatch", "first_invoice"
                ],
            },
            "localoutrank": {
                "name": "LocalOutRank",
                "from_email": "dutch@localoutrank.com",
                "from_name": "Dutch",
                "milestones": [
                    "ran_audit", "viewed_report", "applied_first_recommendation"
                ],
            },
        },
    }


# ---------------------------------------------------------------------------
# OnboardingDB
# ---------------------------------------------------------------------------

class TestOnboardingDB:

    def _make_db_with_mock_conn(self):
        db = OnboardingDB.__new__(OnboardingDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        return db, mock_conn, mock_cur

    def test_upsert_state_returns_id(self):
        db, mock_conn, mock_cur = self._make_db_with_mock_conn()
        expected_id = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected_id}
        with patch("agents.onboarding.db.get_db", return_value=mock_conn):
            result = db.upsert_state(
                user_id="user_abc",
                product="starpio",
                current_milestone="connected_gbp",
            )
        assert result == expected_id

    def test_get_state_returns_dict(self):
        db, mock_conn, mock_cur = self._make_db_with_mock_conn()
        mock_cur.fetchone.return_value = _state()
        with patch("agents.onboarding.db.get_db", return_value=mock_conn):
            result = db.get_state(user_id="user_abc", product="starpio")
        assert result is not None
        assert result["user_id"] == "user_abc"

    def test_get_state_returns_none_when_missing(self):
        db, mock_conn, mock_cur = self._make_db_with_mock_conn()
        mock_cur.fetchone.return_value = None
        with patch("agents.onboarding.db.get_db", return_value=mock_conn):
            result = db.get_state(user_id="ghost", product="starpio")
        assert result is None

    def test_record_milestone_returns_id(self):
        db, mock_conn, mock_cur = self._make_db_with_mock_conn()
        expected_id = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected_id}
        with patch("agents.onboarding.db.get_db", return_value=mock_conn):
            result = db.record_milestone(
                user_id="user_abc",
                product="starpio",
                milestone="connected_gbp",
                days_since_signup=1,
            )
        assert result == expected_id

    def test_get_stuck_users_returns_list(self):
        db, mock_conn, mock_cur = self._make_db_with_mock_conn()
        mock_cur.fetchall.return_value = [_state()]
        with patch("agents.onboarding.db.get_db", return_value=mock_conn):
            results = db.get_stuck_users(days_inactive=5)
        assert isinstance(results, list)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# SignupFlow
# ---------------------------------------------------------------------------

class TestSignupFlow:

    def test_trigger_sends_welcome_email(self, mock_db, cfg):
        flow = SignupFlow(mock_db, cfg)
        with patch("agents.onboarding.signup_flow.send_email") as mock_send, \
             patch("agents.onboarding.signup_flow.enqueue_day1_checkin"), \
             patch("agents.onboarding.signup_flow.enqueue_day3_checkin"), \
             patch("agents.onboarding.signup_flow.enqueue_day7_checkin"):
            mock_send.return_value = True
            result = flow.trigger(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
            )
        mock_send.assert_called_once()
        assert result["welcome_sent"] is True

    def test_trigger_creates_onboarding_state(self, mock_db, cfg):
        flow = SignupFlow(mock_db, cfg)
        with patch("agents.onboarding.signup_flow.send_email") as mock_send, \
             patch("agents.onboarding.signup_flow.enqueue_day1_checkin"), \
             patch("agents.onboarding.signup_flow.enqueue_day3_checkin"), \
             patch("agents.onboarding.signup_flow.enqueue_day7_checkin"):
            mock_send.return_value = True
            flow.trigger(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
            )
        mock_db.upsert_state.assert_called_once()

    def test_trigger_enqueues_three_checkins(self, mock_db, cfg):
        flow = SignupFlow(mock_db, cfg)
        with patch("agents.onboarding.signup_flow.send_email") as mock_send, \
             patch("agents.onboarding.signup_flow.enqueue_day1_checkin") as mock_d1, \
             patch("agents.onboarding.signup_flow.enqueue_day3_checkin") as mock_d3, \
             patch("agents.onboarding.signup_flow.enqueue_day7_checkin") as mock_d7:
            mock_send.return_value = True
            flow.trigger(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
            )
        mock_d1.assert_called_once_with(user_id="user_abc", user_email="user@test.com", product="starpio")
        mock_d3.assert_called_once_with(user_id="user_abc", user_email="user@test.com", product="starpio")
        mock_d7.assert_called_once_with(user_id="user_abc", user_email="user@test.com", product="starpio")

    def test_trigger_welcome_email_from_dutch(self, mock_db, cfg):
        flow = SignupFlow(mock_db, cfg)
        with patch("agents.onboarding.signup_flow.send_email") as mock_send, \
             patch("agents.onboarding.signup_flow.enqueue_day1_checkin"), \
             patch("agents.onboarding.signup_flow.enqueue_day3_checkin"), \
             patch("agents.onboarding.signup_flow.enqueue_day7_checkin"):
            mock_send.return_value = True
            flow.trigger(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
            )
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["from_name"] == "Dutch"

    def test_trigger_sets_first_milestone_as_current(self, mock_db, cfg):
        flow = SignupFlow(mock_db, cfg)
        with patch("agents.onboarding.signup_flow.send_email") as mock_send, \
             patch("agents.onboarding.signup_flow.enqueue_day1_checkin"), \
             patch("agents.onboarding.signup_flow.enqueue_day3_checkin"), \
             patch("agents.onboarding.signup_flow.enqueue_day7_checkin"):
            mock_send.return_value = True
            flow.trigger(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
            )
        upsert_call = mock_db.upsert_state.call_args.kwargs
        assert upsert_call["current_milestone"] == "connected_gbp"

    def test_trigger_result_has_required_keys(self, mock_db, cfg):
        flow = SignupFlow(mock_db, cfg)
        with patch("agents.onboarding.signup_flow.send_email") as mock_send, \
             patch("agents.onboarding.signup_flow.enqueue_day1_checkin"), \
             patch("agents.onboarding.signup_flow.enqueue_day3_checkin"), \
             patch("agents.onboarding.signup_flow.enqueue_day7_checkin"):
            mock_send.return_value = True
            result = flow.trigger(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
            )
        for key in ("user_id", "product", "welcome_sent", "checkins_scheduled"):
            assert key in result


# ---------------------------------------------------------------------------
# ActivationNudge
# ---------------------------------------------------------------------------

class TestActivationNudge:

    def test_nudge_sends_email_when_milestone_overdue(self, mock_db, cfg):
        nudge = ActivationNudge(mock_db, cfg)
        mock_db.get_state.return_value = _state({
            "current_milestone": "first_review_seen",
            "milestones_completed": ["connected_gbp"],
            "last_nudge_at": None,
        })
        with patch("agents.onboarding.activation_nudge.send_email") as mock_send, \
             patch("agents.onboarding.activation_nudge.hours_since", return_value=50):
            mock_send.return_value = True
            result = nudge.check(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
            )
        mock_send.assert_called_once()
        assert result["nudge_sent"] is True

    def test_nudge_skipped_when_milestone_recent(self, mock_db, cfg):
        nudge = ActivationNudge(mock_db, cfg)
        mock_db.get_state.return_value = _state({
            "current_milestone": "first_review_seen",
            "milestones_completed": ["connected_gbp"],
            "last_nudge_at": datetime.now(timezone.utc).isoformat(),
        })
        with patch("agents.onboarding.activation_nudge.send_email") as mock_send, \
             patch("agents.onboarding.activation_nudge.hours_since", return_value=10):
            result = nudge.check(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
            )
        mock_send.assert_not_called()
        assert result["nudge_sent"] is False

    def test_nudge_no_state_skipped(self, mock_db, cfg):
        nudge = ActivationNudge(mock_db, cfg)
        mock_db.get_state.return_value = None
        with patch("agents.onboarding.activation_nudge.send_email") as mock_send:
            result = nudge.check(
                user_id="ghost",
                user_email="ghost@test.com",
                product="starpio",
            )
        mock_send.assert_not_called()
        assert result["nudge_sent"] is False

    def test_nudge_is_single_next_action(self, mock_db, cfg):
        nudge = ActivationNudge(mock_db, cfg)
        mock_db.get_state.return_value = _state({
            "current_milestone": "first_review_seen",
            "milestones_completed": ["connected_gbp"],
            "last_nudge_at": None,
        })
        with patch("agents.onboarding.activation_nudge.send_email") as mock_send, \
             patch("agents.onboarding.activation_nudge.hours_since", return_value=50):
            mock_send.return_value = True
            result = nudge.check(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
            )
        call_kwargs = mock_send.call_args.kwargs
        # Email must reference this specific milestone (by label, not internal key)
        assert "review" in call_kwargs["subject"].lower() or "review" in call_kwargs["html"].lower()

    def test_nudge_updates_last_nudge_at_after_send(self, mock_db, cfg):
        nudge = ActivationNudge(mock_db, cfg)
        mock_db.get_state.return_value = _state({
            "current_milestone": "first_review_seen",
            "milestones_completed": ["connected_gbp"],
            "last_nudge_at": None,
        })
        with patch("agents.onboarding.activation_nudge.send_email") as mock_send, \
             patch("agents.onboarding.activation_nudge.hours_since", return_value=50):
            mock_send.return_value = True
            nudge.check(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
            )
        mock_db.upsert_state.assert_called_once()

    def test_milestone_map_oneserv(self, mock_db, cfg):
        nudge = ActivationNudge(mock_db, cfg)
        mock_db.get_state.return_value = _state({
            "product": "oneserv",
            "current_milestone": "first_job",
            "milestones_completed": ["created_account"],
            "last_nudge_at": None,
        })
        with patch("agents.onboarding.activation_nudge.send_email") as mock_send, \
             patch("agents.onboarding.activation_nudge.hours_since", return_value=50):
            mock_send.return_value = True
            result = nudge.check(
                user_id="user_abc",
                user_email="user@test.com",
                product="oneserv",
            )
        assert result["milestone"] == "first_job"

    def test_milestone_map_localoutrank(self, mock_db, cfg):
        nudge = ActivationNudge(mock_db, cfg)
        mock_db.get_state.return_value = _state({
            "product": "localoutrank",
            "current_milestone": "viewed_report",
            "milestones_completed": ["ran_audit"],
            "last_nudge_at": None,
        })
        with patch("agents.onboarding.activation_nudge.send_email") as mock_send, \
             patch("agents.onboarding.activation_nudge.hours_since", return_value=50):
            mock_send.return_value = True
            result = nudge.check(
                user_id="user_abc",
                user_email="user@test.com",
                product="localoutrank",
            )
        assert result["milestone"] == "viewed_report"


# ---------------------------------------------------------------------------
# FirstValueMoment
# ---------------------------------------------------------------------------

class TestFirstValueMoment:

    def test_celebrate_sends_email_with_outcome(self, mock_db, cfg):
        fvm = FirstValueMoment(mock_db, cfg)
        with patch("agents.onboarding.first_value.send_email") as mock_send, \
             patch("agents.onboarding.first_value.enqueue_nps_survey"):
            mock_send.return_value = True
            result = fvm.celebrate(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
                milestone="first_response_sent",
                days_since_signup=2,
            )
        mock_send.assert_called_once()
        assert result["celebrated"] is True

    def test_celebrate_records_milestone_in_db(self, mock_db, cfg):
        fvm = FirstValueMoment(mock_db, cfg)
        with patch("agents.onboarding.first_value.send_email") as mock_send, \
             patch("agents.onboarding.first_value.enqueue_nps_survey"):
            mock_send.return_value = True
            fvm.celebrate(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
                milestone="first_response_sent",
                days_since_signup=2,
            )
        mock_db.record_milestone.assert_called_once_with(
            user_id="user_abc",
            product="starpio",
            milestone="first_response_sent",
            days_since_signup=2,
        )

    def test_celebrate_updates_current_milestone(self, mock_db, cfg):
        fvm = FirstValueMoment(mock_db, cfg)
        mock_db.get_state.return_value = _state({
            "current_milestone": "connected_gbp",
            "milestones_completed": [],
        })
        with patch("agents.onboarding.first_value.send_email") as mock_send, \
             patch("agents.onboarding.first_value.enqueue_nps_survey"):
            mock_send.return_value = True
            fvm.celebrate(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
                milestone="connected_gbp",
                days_since_signup=0,
            )
        mock_db.upsert_state.assert_called_once()
        upsert_kwargs = mock_db.upsert_state.call_args.kwargs
        assert upsert_kwargs["current_milestone"] == "first_review_seen"

    def test_celebrate_starpio_email_shows_ai_response_copy(self, mock_db, cfg):
        fvm = FirstValueMoment(mock_db, cfg)
        with patch("agents.onboarding.first_value.send_email") as mock_send, \
             patch("agents.onboarding.first_value.enqueue_nps_survey"):
            mock_send.return_value = True
            fvm.celebrate(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
                milestone="first_response_sent",
                days_since_signup=2,
            )
        call_kwargs = mock_send.call_args.kwargs
        assert "AI response" in call_kwargs["html"] or "live" in call_kwargs["html"]

    def test_celebrate_oneserv_email_shows_work_order_copy(self, mock_db, cfg):
        fvm = FirstValueMoment(mock_db, cfg)
        with patch("agents.onboarding.first_value.send_email") as mock_send, \
             patch("agents.onboarding.first_value.enqueue_nps_survey"):
            mock_send.return_value = True
            fvm.celebrate(
                user_id="user_abc",
                user_email="user@test.com",
                product="oneserv",
                milestone="first_dispatch",
                days_since_signup=1,
            )
        call_kwargs = mock_send.call_args.kwargs
        assert "work order" in call_kwargs["html"].lower() or "dispatched" in call_kwargs["html"].lower()

    def test_celebrate_at_30_days_enqueues_nps(self, mock_db, cfg):
        fvm = FirstValueMoment(mock_db, cfg)
        with patch("agents.onboarding.first_value.send_email") as mock_send, \
             patch("agents.onboarding.first_value.enqueue_nps_survey") as mock_nps:
            mock_send.return_value = True
            fvm.celebrate(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
                milestone="first_response_sent",
                days_since_signup=30,
            )
        mock_nps.assert_called_once_with(
            user_id="user_abc",
            user_email="user@test.com",
            product="starpio",
        )

    def test_celebrate_before_30_days_does_not_enqueue_nps(self, mock_db, cfg):
        fvm = FirstValueMoment(mock_db, cfg)
        with patch("agents.onboarding.first_value.send_email") as mock_send, \
             patch("agents.onboarding.first_value.enqueue_nps_survey") as mock_nps:
            mock_send.return_value = True
            fvm.celebrate(
                user_id="user_abc",
                user_email="user@test.com",
                product="starpio",
                milestone="connected_gbp",
                days_since_signup=1,
            )
        mock_nps.assert_not_called()


# ---------------------------------------------------------------------------
# StuckUserAlert
# ---------------------------------------------------------------------------

class TestStuckUserAlert:

    def test_detect_returns_stuck_users(self, mock_db, cfg):
        alert = StuckUserAlert(mock_db, cfg)
        mock_db.get_stuck_users.return_value = [
            _state({"user_id": "u1"}),
            _state({"user_id": "u2"}),
        ]
        with patch("agents.onboarding.stuck_user.send_email") as mock_send:
            mock_send.return_value = True
            result = alert.detect_and_alert(user_lookup={"u1": "u1@test.com", "u2": "u2@test.com"})
        assert result["stuck_count"] == 2
        assert mock_send.call_count == 2

    def test_detect_no_stuck_users_sends_no_email(self, mock_db, cfg):
        alert = StuckUserAlert(mock_db, cfg)
        mock_db.get_stuck_users.return_value = []
        with patch("agents.onboarding.stuck_user.send_email") as mock_send:
            result = alert.detect_and_alert(user_lookup={})
        mock_send.assert_not_called()
        assert result["stuck_count"] == 0

    def test_personal_email_from_dutch(self, mock_db, cfg):
        alert = StuckUserAlert(mock_db, cfg)
        mock_db.get_stuck_users.return_value = [_state({"user_id": "u1"})]
        with patch("agents.onboarding.stuck_user.send_email") as mock_send:
            mock_send.return_value = True
            alert.detect_and_alert(user_lookup={"u1": "u1@test.com"})
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["from_name"] == "Dutch"

    def test_email_has_reply_to_dutch(self, mock_db, cfg):
        alert = StuckUserAlert(mock_db, cfg)
        mock_db.get_stuck_users.return_value = [_state({"user_id": "u1"})]
        with patch("agents.onboarding.stuck_user.send_email") as mock_send:
            mock_send.return_value = True
            alert.detect_and_alert(user_lookup={"u1": "u1@test.com"})
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs.get("reply_to") == cfg["dutch_reply_to"]

    def test_email_is_personal_tone_not_feature_list(self, mock_db, cfg):
        alert = StuckUserAlert(mock_db, cfg)
        mock_db.get_stuck_users.return_value = [_state({"user_id": "u1"})]
        with patch("agents.onboarding.stuck_user.send_email") as mock_send:
            mock_send.return_value = True
            alert.detect_and_alert(user_lookup={"u1": "u1@test.com"})
        html = mock_send.call_args.kwargs["html"]
        # Personal tone: should reference the user signing up and wanting to hear from them
        assert "signed up" in html.lower() or "heard from you" in html.lower()

    def test_skips_user_with_no_email_in_lookup(self, mock_db, cfg):
        alert = StuckUserAlert(mock_db, cfg)
        mock_db.get_stuck_users.return_value = [
            _state({"user_id": "u1"}),
            _state({"user_id": "u2"}),
        ]
        with patch("agents.onboarding.stuck_user.send_email") as mock_send:
            mock_send.return_value = True
            result = alert.detect_and_alert(user_lookup={"u1": "u1@test.com"})
        assert mock_send.call_count == 1
        assert result["alerted"] == 1


# ---------------------------------------------------------------------------
# OnboardingAudit
# ---------------------------------------------------------------------------

class TestOnboardingAudit:

    def test_audit_returns_funnel_metrics(self, mock_db, cfg):
        audit = OnboardingAudit(mock_db, cfg)
        with patch("agents.onboarding.audit.llm") as mock_llm, \
             patch("agents.onboarding.audit.enqueue_content_task"), \
             patch("agents.onboarding.audit.enqueue_dev_task"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "biggest_dropoff_step": "first_review_seen",
                    "proposal": "Rewrite the empty-state copy on the Reviews tab",
                    "action_type": "content",
                }))
            ]
            result = audit.run(product="starpio")
        assert "signup_to_activated_pct" in result
        assert "biggest_dropoff_step" in result

    def test_audit_identifies_biggest_dropoff_via_llm(self, mock_db, cfg):
        audit = OnboardingAudit(mock_db, cfg)
        with patch("agents.onboarding.audit.llm") as mock_llm, \
             patch("agents.onboarding.audit.enqueue_content_task"), \
             patch("agents.onboarding.audit.enqueue_dev_task"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "biggest_dropoff_step": "first_review_seen",
                    "proposal": "Add a sample review to the empty state",
                    "action_type": "content",
                }))
            ]
            result = audit.run(product="starpio")
        assert result["biggest_dropoff_step"] == "first_review_seen"
        mock_llm.complete.assert_called_once()

    def test_audit_enqueues_content_task_on_copy_proposal(self, mock_db, cfg):
        audit = OnboardingAudit(mock_db, cfg)
        with patch("agents.onboarding.audit.llm") as mock_llm, \
             patch("agents.onboarding.audit.enqueue_content_task") as mock_ct, \
             patch("agents.onboarding.audit.enqueue_dev_task"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "biggest_dropoff_step": "first_review_seen",
                    "proposal": "Rewrite empty-state copy",
                    "action_type": "content",
                }))
            ]
            audit.run(product="starpio")
        mock_ct.assert_called_once()

    def test_audit_enqueues_dev_task_on_flow_proposal(self, mock_db, cfg):
        audit = OnboardingAudit(mock_db, cfg)
        with patch("agents.onboarding.audit.llm") as mock_llm, \
             patch("agents.onboarding.audit.enqueue_content_task"), \
             patch("agents.onboarding.audit.enqueue_dev_task") as mock_dt:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "biggest_dropoff_step": "connected_gbp",
                    "proposal": "Add auto-connect OAuth flow for GBP",
                    "action_type": "dev",
                }))
            ]
            audit.run(product="starpio")
        mock_dt.assert_called_once()

    def test_audit_result_has_required_keys(self, mock_db, cfg):
        audit = OnboardingAudit(mock_db, cfg)
        with patch("agents.onboarding.audit.llm") as mock_llm, \
             patch("agents.onboarding.audit.enqueue_content_task"), \
             patch("agents.onboarding.audit.enqueue_dev_task"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "biggest_dropoff_step": "first_review_seen",
                    "proposal": "Something",
                    "action_type": "content",
                }))
            ]
            result = audit.run(product="starpio")
        for key in (
            "product", "signup_to_activated_pct", "biggest_dropoff_step",
            "proposal", "action_type",
        ):
            assert key in result


# ---------------------------------------------------------------------------
# OnboardingAgent dispatch
# ---------------------------------------------------------------------------

class TestOnboardingAgent:

    @pytest.fixture
    def agent(self, cfg):
        from agents.onboarding.main import OnboardingAgent
        config = MagicMock(spec=AgentConfig)
        config.custom = cfg
        config.llm_system_prompt = ""
        config.poll_interval_seconds = 2
        with patch("agents.onboarding.main.OnboardingDB"), \
             patch("agents.onboarding.main.SignupFlow"), \
             patch("agents.onboarding.main.ActivationNudge"), \
             patch("agents.onboarding.main.FirstValueMoment"), \
             patch("agents.onboarding.main.StuckUserAlert"), \
             patch("agents.onboarding.main.OnboardingAudit"):
            return OnboardingAgent("onboarding", config)

    def test_unknown_action_returns_error(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "teleport_user"},
        )
        result = agent.handle(task)
        assert result.success is False
        assert "error" in result.output

    def test_new_signup_flow_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "new_signup_flow",
                "user_id": "user_abc",
                "user_email": "user@test.com",
                "product": "starpio",
            },
        )
        agent._signup_flow.trigger.return_value = {
            "welcome_sent": True,
            "checkins_scheduled": 3,
        }
        result = agent.handle(task)
        assert result.success is True
        agent._signup_flow.trigger.assert_called_once()

    def test_activation_nudge_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "activation_nudge",
                "user_id": "user_abc",
                "user_email": "user@test.com",
                "product": "starpio",
            },
        )
        agent._nudge.check.return_value = {"nudge_sent": True, "milestone": "first_review_seen"}
        result = agent.handle(task)
        assert result.success is True
        agent._nudge.check.assert_called_once()

    def test_first_value_moment_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "first_value_moment",
                "user_id": "user_abc",
                "user_email": "user@test.com",
                "product": "starpio",
                "milestone": "first_response_sent",
                "days_since_signup": 2,
            },
        )
        agent._first_value.celebrate.return_value = {"celebrated": True}
        result = agent.handle(task)
        assert result.success is True
        agent._first_value.celebrate.assert_called_once()

    def test_stuck_user_alert_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "stuck_user_alert",
                "user_lookup": {"u1": "u1@test.com"},
            },
        )
        agent._stuck_alert.detect_and_alert.return_value = {"stuck_count": 1, "alerted": 1}
        result = agent.handle(task)
        assert result.success is True
        agent._stuck_alert.detect_and_alert.assert_called_once()

    def test_onboarding_audit_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "onboarding_audit",
                "product": "starpio",
            },
        )
        agent._audit.run.return_value = {
            "product": "starpio",
            "signup_to_activated_pct": 42.0,
            "biggest_dropoff_step": "first_review_seen",
            "proposal": "Rewrite copy",
            "action_type": "content",
        }
        result = agent.handle(task)
        assert result.success is True
        agent._audit.run.assert_called_once()

    def test_health_check_true_when_db_ok(self, agent):
        agent._db.get_stuck_users.return_value = []
        assert agent.health_check() is True

    def test_health_check_false_on_db_error(self, agent):
        agent._db.get_stuck_users.side_effect = Exception("db down")
        assert agent.health_check() is False
