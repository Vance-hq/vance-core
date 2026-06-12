"""Outreach agent unit tests — no external services required."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from agents._base import AgentConfig
from agents.outreach.db import OutreachDB
from agents.outreach.scorer import ContactScorer
from agents.outreach.sequence_mgr import SequenceManager, _STEPS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    return MagicMock(spec=OutreachDB)


@pytest.fixture
def agent_config():
    return AgentConfig(
        agent_name="outreach",
        custom={
            "scoring_weights": {
                "replies": 30,
                "email_clicks": 20,
                "linkedin_activity": 25,
                "email_opens": 10,
                "role_fit": 10,
                "company_size": 5,
            },
            "scoring_tiers": {"hot": 70, "warm": 40},
            "outreach_from_email": "test@example.com",
            "outreach_from_name": "Dutch",
            "outreach_from_password": "secret",
        },
    )


@pytest.fixture
def contact_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# ContactScorer
# ---------------------------------------------------------------------------

class TestContactScorer:

    def test_hot_lead(self):
        scorer = ContactScorer()
        result = scorer.score(
            contact_id="abc",
            product="oneserv",
            role="owner",
            company_size="1-10",
            email_opens=5,
            email_clicks=3,
            replies=2,
            linkedin_activity=2,
        )
        assert result["tier"] == "HOT"
        assert result["score"] >= 70
        assert result["recommended_next_action"] == "book_call"

    def test_cold_lead_no_engagement(self):
        scorer = ContactScorer()
        result = scorer.score(
            contact_id="abc",
            product="starpio",
            role="unknown",
            company_size="",
            email_opens=0,
            email_clicks=0,
            replies=0,
            linkedin_activity=0,
        )
        assert result["tier"] == "COLD"
        assert result["score"] < 40

    def test_warm_lead_some_engagement(self):
        scorer = ContactScorer()
        result = scorer.score(
            contact_id="abc",
            product="localoutrank",
            role="owner",
            company_size="1-50",
            email_opens=5,
            email_clicks=2,
            replies=0,
            linkedin_activity=1,
        )
        assert result["tier"] in ("WARM", "HOT")

    def test_score_capped_at_100(self):
        scorer = ContactScorer()
        result = scorer.score(
            contact_id="abc",
            product="oneserv",
            role="owner",
            company_size="1-10",
            email_opens=100,
            email_clicks=100,
            replies=100,
            linkedin_activity=100,
        )
        assert result["score"] <= 100

    def test_custom_weights_applied(self):
        scorer = ContactScorer(weights={"replies": 100, "email_opens": 0, "email_clicks": 0,
                                        "linkedin_activity": 0, "role_fit": 0, "company_size": 0})
        result_reply = scorer.score("a", "starpio", "owner", "", 5, 5, 1, 0)
        result_no_reply = scorer.score("b", "starpio", "owner", "", 5, 5, 0, 0)
        assert result_reply["score"] > result_no_reply["score"]

    def test_no_linkedin_products_still_score(self):
        scorer = ContactScorer()
        result = scorer.score(
            contact_id="abc",
            product="trusted_plumbing",
            role="homeowner",
            company_size="",
            email_opens=2,
            email_clicks=1,
            replies=0,
            linkedin_activity=0,
        )
        assert isinstance(result["score"], int)

    def test_role_fit_owner(self):
        scorer = ContactScorer()
        result_owner = scorer.score("a", "oneserv", "hvac owner", "", 0, 0, 0, 0)
        result_random = scorer.score("b", "oneserv", "marketing intern", "", 0, 0, 0, 0)
        assert result_owner["score"] >= result_random["score"]


# ---------------------------------------------------------------------------
# SequenceManager
# ---------------------------------------------------------------------------

class TestSequenceManager:

    def test_start_creates_sequence(self, mock_db, contact_id):
        mock_db.upsert_sequence.return_value = str(uuid.uuid4())
        mock_db.get_sequence.return_value = {
            "status": "ACTIVE",
            "current_step": 0,
            "contact_id": contact_id,
        }
        mock_db.get_contact.return_value = {
            "id": contact_id,
            "email": "test@example.com",
            "linkedin_url": "https://linkedin.com/in/test",
            "name": "Test User",
            "company": "Test Co",
            "role": "owner",
            "research_notes": "",
        }

        with patch("agents.outreach.sequence_mgr.TaskQueue") as MockQueue:
            mgr = SequenceManager(mock_db)
            result = mgr.start(contact_id, "oneserv")

        assert result["status"] == "started"
        assert result["first_step"] == 0

    def test_no_linkedin_product_starts_at_step_2(self, mock_db, contact_id):
        mock_db.upsert_sequence.return_value = str(uuid.uuid4())
        mock_db.get_sequence.return_value = {
            "status": "ACTIVE",
            "current_step": 0,
            "contact_id": contact_id,
        }
        mock_db.get_contact.return_value = {
            "id": contact_id,
            "email": "test@example.com",
            "linkedin_url": None,
            "name": "Test",
            "company": "Test Co",
            "role": "owner",
            "research_notes": "",
        }

        with patch("agents.outreach.sequence_mgr.TaskQueue"):
            mgr = SequenceManager(mock_db)
            result = mgr.start(contact_id, "trusted_plumbing")

        assert result["first_step"] == 2

    def test_complete_step_advances_sequence(self, mock_db, contact_id):
        mock_db.get_sequence.return_value = {
            "status": "ACTIVE",
            "current_step": 0,
            "contact_id": contact_id,
        }
        mock_db.get_contact.return_value = {
            "id": contact_id,
            "email": "test@example.com",
            "linkedin_url": "https://linkedin.com/in/test",
            "name": "Test",
            "company": "Co",
            "role": "owner",
            "research_notes": "",
        }

        with patch("agents.outreach.sequence_mgr.TaskQueue"):
            mgr = SequenceManager(mock_db)
            result = mgr.complete_step(contact_id, "oneserv")

        assert result["status"] == "advanced"
        assert result["next_step"] == 1

    def test_complete_last_step_completes_sequence(self, mock_db, contact_id):
        last = len(_STEPS) - 1
        mock_db.get_sequence.return_value = {
            "status": "ACTIVE",
            "current_step": last,
            "contact_id": contact_id,
        }

        with patch("agents.outreach.sequence_mgr.TaskQueue"):
            mgr = SequenceManager(mock_db)
            result = mgr.complete_step(contact_id, "oneserv")

        assert result["status"] == "complete"
        mock_db.complete_sequence.assert_called_once_with(contact_id)

    def test_opt_out_stops_sequence(self, mock_db, contact_id):
        with patch("agents.outreach.sequence_mgr.TaskQueue"):
            mgr = SequenceManager(mock_db)
            result = mgr.opt_out(contact_id)

        assert result["status"] == "opted_out"
        mock_db.opt_out_sequence.assert_called_once_with(contact_id)
        mock_db.mark_unsubscribed.assert_called_once_with(contact_id)

    def test_opted_out_sequence_not_restarted(self, mock_db, contact_id):
        mock_db.upsert_sequence.return_value = str(uuid.uuid4())
        mock_db.get_sequence.return_value = {
            "status": "OPTED_OUT",
            "current_step": 2,
            "contact_id": contact_id,
        }

        with patch("agents.outreach.sequence_mgr.TaskQueue"):
            mgr = SequenceManager(mock_db)
            result = mgr.start(contact_id, "oneserv")

        assert result["status"] == "OPTED_OUT"


# ---------------------------------------------------------------------------
# OutreachAgent dispatch
# ---------------------------------------------------------------------------

class TestOutreachAgentDispatch:

    def test_unknown_action_raises(self, agent_config, contact_id):
        from agents.outreach.main import OutreachAgent
        from shared.types import AgentCapability, Task

        with patch("agents.outreach.main.OutreachDB"), \
             patch("agents.outreach.main.ContactResearcher"), \
             patch("agents.outreach.main.SequenceManager"), \
             patch("agents.outreach.main.FollowupMailer"), \
             patch("agents._base.agent.redis.Redis"), \
             patch("agents._base.agent.TaskQueue"):
            agent = OutreachAgent("outreach", agent_config)
            task = Task(id=str(uuid.uuid4()), agent=AgentCapability.OUTREACH,
                        payload={"action": "nonexistent_action"})
            with pytest.raises(ValueError, match="Unknown outreach action"):
                agent.handle(task)

    def test_linkedin_disabled_for_trusted_plumbing(self, agent_config, contact_id):
        from agents.outreach.main import OutreachAgent
        from shared.types import AgentCapability, Task

        with patch("agents.outreach.main.OutreachDB") as MockDB, \
             patch("agents.outreach.main.ContactResearcher"), \
             patch("agents.outreach.main.SequenceManager"), \
             patch("agents.outreach.main.FollowupMailer"), \
             patch("agents._base.agent.redis.Redis"), \
             patch("agents._base.agent.TaskQueue"):
            MockDB.return_value.is_unsubscribed.return_value = False
            MockDB.return_value.linkedin_connect_sent.return_value = False
            agent = OutreachAgent("outreach", agent_config)
            task = Task(
                id=str(uuid.uuid4()),
                agent=AgentCapability.OUTREACH,
                payload={
                    "action": "linkedin_connect",
                    "contact_id": contact_id,
                    "product": "trusted_plumbing",
                    "linkedin_url": "https://linkedin.com/in/test",
                    "name": "Test",
                    "company": "Test Co",
                    "role": "owner",
                },
            )
            result = agent.handle(task)
            assert result.output["sent"] is False
            assert result.output["reason"] == "linkedin_disabled_for_product"

    def test_lead_score_contact_not_found(self, agent_config, contact_id):
        from agents.outreach.main import OutreachAgent
        from shared.types import AgentCapability, Task

        with patch("agents.outreach.main.OutreachDB") as MockDB, \
             patch("agents.outreach.main.ContactResearcher"), \
             patch("agents.outreach.main.SequenceManager"), \
             patch("agents.outreach.main.FollowupMailer"), \
             patch("agents._base.agent.redis.Redis"), \
             patch("agents._base.agent.TaskQueue"):
            MockDB.return_value.get_contact.return_value = None
            agent = OutreachAgent("outreach", agent_config)
            task = Task(
                id=str(uuid.uuid4()),
                agent=AgentCapability.OUTREACH,
                payload={"action": "lead_score", "contact_id": contact_id, "product": "oneserv"},
            )
            result = agent.handle(task)
            assert "error" in result.output

    def test_email_followup_unsubscribed(self, agent_config, contact_id):
        from agents.outreach.main import OutreachAgent
        from shared.types import AgentCapability, Task

        with patch("agents.outreach.main.OutreachDB") as MockDB, \
             patch("agents.outreach.main.ContactResearcher"), \
             patch("agents.outreach.main.SequenceManager"), \
             patch("agents.outreach.main.FollowupMailer"), \
             patch("agents._base.agent.redis.Redis"), \
             patch("agents._base.agent.TaskQueue"):
            MockDB.return_value.get_contact.return_value = {
                "id": contact_id, "email": "test@example.com", "name": "Test"
            }
            MockDB.return_value.is_unsubscribed.return_value = True
            agent = OutreachAgent("outreach", agent_config)
            task = Task(
                id=str(uuid.uuid4()),
                agent=AgentCapability.OUTREACH,
                payload={
                    "action": "email_followup",
                    "contact_id": contact_id,
                    "product": "starpio",
                    "original_email": "hi",
                    "their_reply": "interested",
                },
            )
            result = agent.handle(task)
            assert result.output["sent"] is False
            assert result.output["reason"] == "contact_unsubscribed"


# ---------------------------------------------------------------------------
# OutreachDB throttle logic (unit-level)
# ---------------------------------------------------------------------------

class TestOutreachDB:

    def test_hours_since_returns_inf_when_no_record(self):
        db = OutreachDB.__new__(OutreachDB)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = None
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor

        with patch("agents.outreach.db.get_db", return_value=mock_conn):
            result = db.hours_since_last_linkedin_message("some-contact-id")

        assert result == float("inf")
