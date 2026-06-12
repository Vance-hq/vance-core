"""Support agent unit tests — no external services required."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from agents._base import AgentConfig
from agents.support.db import SupportDB
from agents.support.ticket_handler import TicketHandler
from agents.support.auto_resolver import AutoResolver
from agents.support.kb_manager import KBManager
from agents.support.proactive_monitor import ProactiveMonitor
from agents.support.nps_manager import NpsManager
from shared.types import AgentCapability, Task, TaskResult


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _ticket(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "product": "localoutrank",
        "user_id": "user_abc",
        "channel": "email",
        "classification": "HOW_TO",
        "subject": "How do I add a keyword?",
        "body": "I can't figure out how to add a keyword to my account.",
        "status": "open",
        "resolved_at": None,
        "auto_resolved": False,
    }
    if overrides:
        base.update(overrides)
    return base


def _nps(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "user_id": "user_abc",
        "product": "localoutrank",
        "score": 9,
        "comment": "Great product!",
        "recorded_at": datetime.now(timezone.utc),
    }
    if overrides:
        base.update(overrides)
    return base


def _kb_article(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "product": "localoutrank",
        "title": "How to add a keyword",
        "body": "Navigate to Keywords > Add New...",
        "source_ticket_ids": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    if overrides:
        base.update(overrides)
    return base


@pytest.fixture
def mock_db():
    db = MagicMock(spec=SupportDB)
    db.save_ticket.return_value = str(uuid.uuid4())
    db.get_ticket.return_value = _ticket()
    db.list_resolved_tickets.return_value = [_ticket({"status": "resolved"})]
    db.save_kb_article.return_value = str(uuid.uuid4())
    db.search_kb.return_value = [_kb_article()]
    db.save_nps_response.return_value = str(uuid.uuid4())
    db.get_nps_responses.return_value = [_nps()]
    return db


@pytest.fixture
def cfg() -> dict:
    return {
        "resend_api_key": "re_test_key",
        "crisp_website_id": "crisp_site_abc",
        "crisp_token": "crisp_token_abc",
        "stripe_api_key": "sk_test_abc",
        "supabase_url": "https://proj.supabase.co",
        "supabase_service_key": "service_key_abc",
        "github_token": "ghp_test",
        "github_repo": "vance-hq/vance-core",
        "docs_repo_path": "/tmp/docs",
        "nps_from_email": "nps@localoutrank.com",
        "products": {
            "localoutrank": {
                "name": "LocalOutRank",
                "support_email": "support@localoutrank.com",
                "from_name": "LocalOutRank Support",
            },
            "starpio": {
                "name": "Starpio",
                "support_email": "support@starpio.com",
                "from_name": "Starpio Support",
            },
        },
    }


# ---------------------------------------------------------------------------
# SupportDB
# ---------------------------------------------------------------------------

class TestSupportDB:

    def test_save_ticket_returns_id(self):
        db = SupportDB.__new__(SupportDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        expected_id = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected_id}

        with patch("agents.support.db.get_db", return_value=mock_conn):
            result = db.save_ticket(
                product="localoutrank",
                user_id="user_abc",
                channel="email",
                classification="HOW_TO",
                subject="Test",
                body="Test body",
            )
        assert result == expected_id

    def test_update_ticket_status(self):
        db = SupportDB.__new__(SupportDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur

        with patch("agents.support.db.get_db", return_value=mock_conn):
            db.update_ticket(ticket_id="t1", status="resolved", auto_resolved=True)

        mock_cur.execute.assert_called_once()

    def test_save_nps_response_returns_id(self):
        db = SupportDB.__new__(SupportDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        expected_id = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected_id}

        with patch("agents.support.db.get_db", return_value=mock_conn):
            result = db.save_nps_response(
                user_id="user_abc",
                product="localoutrank",
                score=9,
                comment="Love it",
            )
        assert result == expected_id

    def test_save_kb_article_returns_id(self):
        db = SupportDB.__new__(SupportDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        expected_id = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected_id}

        with patch("agents.support.db.get_db", return_value=mock_conn):
            result = db.save_kb_article(
                product="localoutrank",
                title="How to add keywords",
                body="Step 1...",
                source_ticket_ids=["t1", "t2"],
            )
        assert result == expected_id

    def test_list_resolved_tickets_limit(self):
        db = SupportDB.__new__(SupportDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchall.return_value = [_ticket({"status": "resolved"})] * 3

        with patch("agents.support.db.get_db", return_value=mock_conn):
            results = db.list_resolved_tickets(product="localoutrank", limit=3)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# TicketHandler
# ---------------------------------------------------------------------------

class TestTicketHandler:

    def test_classify_bug(self, mock_db, cfg):
        handler = TicketHandler(mock_db, cfg)
        with patch("agents.support.ticket_handler.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="BUG")
            ]
            cls = handler._classify("App crashes on login", "Getting a 500 error")
        assert cls == "BUG"

    def test_classify_returns_uppercase(self, mock_db, cfg):
        handler = TicketHandler(mock_db, cfg)
        with patch("agents.support.ticket_handler.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="  how_to  ")
            ]
            cls = handler._classify("subject", "body")
        assert cls == "HOW_TO"

    def test_classify_defaults_to_how_to_on_unknown(self, mock_db, cfg):
        handler = TicketHandler(mock_db, cfg)
        with patch("agents.support.ticket_handler.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="NONSENSE_CATEGORY")
            ]
            cls = handler._classify("subject", "body")
        assert cls == "HOW_TO"

    def test_handle_how_to_searches_kb(self, mock_db, cfg):
        handler = TicketHandler(mock_db, cfg)
        mock_db.search_kb.return_value = [_kb_article()]
        with patch("agents.support.ticket_handler.llm") as mock_llm, \
             patch("agents.support.ticket_handler.send_email") as mock_send:
            mock_llm.complete.return_value.content = [MagicMock(text="Here is how to add a keyword...")]
            result = handler.handle(
                product="localoutrank",
                user_id="user_abc",
                channel="email",
                subject="How to add keyword",
                body="I need help",
                user_email="user@test.com",
            )
        mock_db.search_kb.assert_called_once()
        assert result["classification"] == "HOW_TO"
        assert result["ticket_id"] is not None

    def test_handle_bug_creates_github_issue(self, mock_db, cfg):
        handler = TicketHandler(mock_db, cfg)
        with patch("agents.support.ticket_handler.llm") as mock_llm, \
             patch("agents.support.ticket_handler.send_email") as mock_send, \
             patch("agents.support.ticket_handler.httpx") as mock_httpx:
            mock_llm.complete.return_value.content = [MagicMock(text="BUG")]
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"number": 42, "html_url": "https://github.com/vance-hq/vance-core/issues/42"}
            mock_httpx.post.return_value = mock_resp
            result = handler.handle(
                product="localoutrank",
                user_id="user_abc",
                channel="email",
                subject="App crashes",
                body="500 on login",
                user_email="user@test.com",
            )
        mock_httpx.post.assert_called_once()
        assert result["classification"] == "BUG"
        assert result["github_issue"] == 42

    def test_handle_complaint_escalates(self, mock_db, cfg):
        handler = TicketHandler(mock_db, cfg)
        with patch("agents.support.ticket_handler.llm") as mock_llm, \
             patch("agents.support.ticket_handler.send_email") as mock_send, \
             patch("agents.support.ticket_handler.enqueue_escalation") as mock_esc:
            mock_llm.complete.return_value.content = [MagicMock(text="COMPLAINT")]
            result = handler.handle(
                product="localoutrank",
                user_id="user_abc",
                channel="email",
                subject="Very upset",
                body="This is unacceptable",
                user_email="user@test.com",
            )
        mock_esc.assert_called_once()
        assert result["classification"] == "COMPLAINT"

    def test_handle_billing_sends_factual_response(self, mock_db, cfg):
        handler = TicketHandler(mock_db, cfg)
        with patch("agents.support.ticket_handler.llm") as mock_llm, \
             patch("agents.support.ticket_handler.send_email") as mock_send, \
             patch("agents.support.ticket_handler.httpx") as mock_httpx:
            # First call: classify; second call: generate response
            mock_llm.complete.return_value.content = [MagicMock(text="BILLING")]
            stripe_resp = MagicMock()
            stripe_resp.status_code = 200
            stripe_resp.json.return_value = {
                "data": [{"id": "sub_abc", "status": "active", "plan": {"nickname": "Pro"}}]
            }
            mock_httpx.get.return_value = stripe_resp
            result = handler.handle(
                product="localoutrank",
                user_id="user_abc",
                channel="email",
                subject="My bill",
                body="What am I being charged?",
                user_email="user@test.com",
            )
        assert result["classification"] == "BILLING"

    def test_handle_unsubscribe_triggers_deletion(self, mock_db, cfg):
        handler = TicketHandler(mock_db, cfg)
        with patch("agents.support.ticket_handler.llm") as mock_llm, \
             patch("agents.support.ticket_handler.send_email") as mock_send, \
             patch("agents.support.ticket_handler.enqueue_auto_resolve") as mock_ar:
            mock_llm.complete.return_value.content = [MagicMock(text="UNSUBSCRIBE")]
            result = handler.handle(
                product="localoutrank",
                user_id="user_abc",
                channel="email",
                subject="Delete my account",
                body="Please delete everything",
                user_email="user@test.com",
            )
        mock_ar.assert_called_once()
        assert result["classification"] == "UNSUBSCRIBE"

    def test_response_sent_for_every_classification(self, mock_db, cfg):
        handler = TicketHandler(mock_db, cfg)
        for cls in ("HOW_TO", "BILLING", "FEATURE_REQUEST"):
            mock_db.search_kb.return_value = []
            with patch("agents.support.ticket_handler.llm") as mock_llm, \
                 patch("agents.support.ticket_handler.send_email") as mock_send, \
                 patch("agents.support.ticket_handler.httpx") as mock_httpx:
                stripe_resp = MagicMock()
                stripe_resp.status_code = 200
                stripe_resp.json.return_value = {"data": []}
                mock_httpx.get.return_value = stripe_resp
                mock_llm.complete.return_value.content = [MagicMock(text=cls)]
                handler.handle(
                    product="localoutrank",
                    user_id="user_abc",
                    channel="email",
                    subject="subject",
                    body="body",
                    user_email="user@test.com",
                )
            mock_send.assert_called_once()
            mock_send.reset_mock()


# ---------------------------------------------------------------------------
# AutoResolver
# ---------------------------------------------------------------------------

class TestAutoResolver:

    def test_resolve_password_reset_triggers_supabase(self, mock_db, cfg):
        resolver = AutoResolver(mock_db, cfg)
        with patch("agents.support.auto_resolver.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_httpx.post.return_value = mock_resp
            result = resolver.resolve(
                action="password_reset",
                user_id="user_abc",
                user_email="user@test.com",
                product="localoutrank",
            )
        mock_httpx.post.assert_called_once()
        assert result["action"] == "password_reset"
        assert result["success"] is True

    def test_resolve_plan_change_calls_stripe(self, mock_db, cfg):
        resolver = AutoResolver(mock_db, cfg)
        with patch("agents.support.auto_resolver.httpx") as mock_httpx:
            list_resp = MagicMock()
            list_resp.status_code = 200
            list_resp.json.return_value = {"data": [{"id": "sub_abc", "status": "active"}]}
            update_resp = MagicMock()
            update_resp.status_code = 200
            update_resp.json.return_value = {"id": "sub_abc", "status": "active"}
            mock_httpx.get.return_value = list_resp
            mock_httpx.post.return_value = update_resp
            result = resolver.resolve(
                action="plan_change",
                user_id="user_abc",
                user_email="user@test.com",
                product="localoutrank",
                new_plan_id="price_pro_monthly",
            )
        assert result["action"] == "plan_change"
        assert result["success"] is True

    def test_resolve_account_deletion_gdpr(self, mock_db, cfg):
        resolver = AutoResolver(mock_db, cfg)
        with patch("agents.support.auto_resolver.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"user": {"id": "user_abc"}}
            mock_httpx.delete.return_value = mock_resp
            mock_httpx.post.return_value = mock_resp
            result = resolver.resolve(
                action="account_deletion",
                user_id="user_abc",
                user_email="user@test.com",
                product="localoutrank",
            )
        assert result["action"] == "account_deletion"
        assert result["success"] is True

    def test_resolve_subscription_pause_calls_stripe(self, mock_db, cfg):
        resolver = AutoResolver(mock_db, cfg)
        with patch("agents.support.auto_resolver.httpx") as mock_httpx:
            list_resp = MagicMock()
            list_resp.status_code = 200
            list_resp.json.return_value = {"data": [{"id": "sub_abc", "status": "active"}]}
            pause_resp = MagicMock()
            pause_resp.status_code = 200
            pause_resp.json.return_value = {"id": "sub_abc", "pause_collection": {"behavior": "void"}}
            mock_httpx.get.return_value = list_resp
            mock_httpx.post.return_value = pause_resp
            result = resolver.resolve(
                action="subscription_pause",
                user_id="user_abc",
                user_email="user@test.com",
                product="localoutrank",
            )
        assert result["action"] == "subscription_pause"
        assert result["success"] is True

    def test_resolve_logs_auto_resolution(self, mock_db, cfg):
        resolver = AutoResolver(mock_db, cfg)
        with patch("agents.support.auto_resolver.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_httpx.post.return_value = mock_resp
            resolver.resolve(
                action="password_reset",
                user_id="user_abc",
                user_email="user@test.com",
                product="localoutrank",
            )
        mock_db.save_ticket.assert_called_once()

    def test_resolve_unknown_action_returns_error(self, mock_db, cfg):
        resolver = AutoResolver(mock_db, cfg)
        result = resolver.resolve(
            action="teleport_user",
            user_id="user_abc",
            user_email="user@test.com",
            product="localoutrank",
        )
        assert result["success"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# KBManager
# ---------------------------------------------------------------------------

class TestKBManager:

    def test_update_pulls_50_resolved_tickets(self, mock_db, cfg):
        manager = KBManager(mock_db, cfg)
        mock_db.list_resolved_tickets.return_value = [_ticket({"status": "resolved"})] * 5
        with patch("agents.support.kb_manager.llm") as mock_llm, \
             patch("agents.support.kb_manager.KBManager._commit_article"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"title": "How to add a keyword", "body": "Step 1..."}
                ]))
            ]
            result = manager.update(product="localoutrank")
        mock_db.list_resolved_tickets.assert_called_once_with(product="localoutrank", limit=50)
        assert "articles_created" in result

    def test_update_creates_kb_articles(self, mock_db, cfg):
        manager = KBManager(mock_db, cfg)
        mock_db.list_resolved_tickets.return_value = [
            _ticket({"id": "t1", "status": "resolved"}),
            _ticket({"id": "t2", "status": "resolved"}),
        ]
        with patch("agents.support.kb_manager.llm") as mock_llm, \
             patch("agents.support.kb_manager.KBManager._commit_article"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"title": "How to add keywords", "body": "Step 1: Navigate..."},
                    {"title": "How to export data", "body": "Step 1: Click..."},
                ]))
            ]
            result = manager.update(product="localoutrank")
        assert result["articles_created"] == 2
        assert mock_db.save_kb_article.call_count == 2

    def test_update_commits_articles_to_git(self, mock_db, cfg):
        manager = KBManager(mock_db, cfg)
        mock_db.list_resolved_tickets.return_value = [_ticket({"status": "resolved"})]
        with patch("agents.support.kb_manager.llm") as mock_llm, \
             patch("agents.support.kb_manager.KBManager._commit_article") as mock_commit:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"title": "How to add keywords", "body": "Navigate to..."},
                ]))
            ]
            manager.update(product="localoutrank")
        mock_commit.assert_called_once()

    def test_update_returns_zero_when_no_articles(self, mock_db, cfg):
        manager = KBManager(mock_db, cfg)
        mock_db.list_resolved_tickets.return_value = []
        with patch("agents.support.kb_manager.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([]))
            ]
            result = manager.update(product="localoutrank")
        assert result["articles_created"] == 0

    def test_search_kb_returns_articles(self, mock_db, cfg):
        manager = KBManager(mock_db, cfg)
        mock_db.search_kb.return_value = [_kb_article()]
        results = manager.search(product="localoutrank", query="add keyword")
        assert len(results) == 1
        mock_db.search_kb.assert_called_once_with(product="localoutrank", query="add keyword")


# ---------------------------------------------------------------------------
# ProactiveMonitor
# ---------------------------------------------------------------------------

class TestProactiveMonitor:

    def test_monitor_checks_error_rates(self, mock_db, cfg):
        monitor = ProactiveMonitor(mock_db, cfg)
        with patch("agents.support.proactive_monitor.web_search") as mock_search, \
             patch("agents.support.proactive_monitor.llm") as mock_llm, \
             patch("agents.support.proactive_monitor.enqueue_marketing_send") as mock_send:
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({"spike_detected": False, "affected_feature": "", "user_impact": ""}))
            ]
            result = monitor.check(product="localoutrank")
        assert "spike_detected" in result

    def test_monitor_sends_proactive_message_on_spike(self, mock_db, cfg):
        monitor = ProactiveMonitor(mock_db, cfg)
        with patch("agents.support.proactive_monitor.web_search") as mock_search, \
             patch("agents.support.proactive_monitor.llm") as mock_llm, \
             patch("agents.support.proactive_monitor.enqueue_marketing_send") as mock_send:
            mock_search.return_value = [{"content": "500 errors on login page since 2pm"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "spike_detected": True,
                    "affected_feature": "login",
                    "user_impact": "Users cannot log in",
                }))
            ]
            result = monitor.check(product="localoutrank")
        assert result["spike_detected"] is True
        mock_send.assert_called_once()

    def test_monitor_no_send_when_no_spike(self, mock_db, cfg):
        monitor = ProactiveMonitor(mock_db, cfg)
        with patch("agents.support.proactive_monitor.web_search") as mock_search, \
             patch("agents.support.proactive_monitor.llm") as mock_llm, \
             patch("agents.support.proactive_monitor.enqueue_marketing_send") as mock_send:
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({"spike_detected": False, "affected_feature": "", "user_impact": ""}))
            ]
            monitor.check(product="localoutrank")
        mock_send.assert_not_called()

    def test_monitor_result_has_required_keys(self, mock_db, cfg):
        monitor = ProactiveMonitor(mock_db, cfg)
        with patch("agents.support.proactive_monitor.web_search") as mock_search, \
             patch("agents.support.proactive_monitor.llm") as mock_llm, \
             patch("agents.support.proactive_monitor.enqueue_marketing_send"):
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({"spike_detected": False, "affected_feature": "", "user_impact": ""}))
            ]
            result = monitor.check(product="localoutrank")
        for key in ("product", "spike_detected", "affected_feature"):
            assert key in result


# ---------------------------------------------------------------------------
# NpsManager
# ---------------------------------------------------------------------------

class TestNpsManager:

    def test_send_survey_sends_email(self, mock_db, cfg):
        manager = NpsManager(mock_db, cfg)
        with patch("agents.support.nps_manager.send_email") as mock_send:
            mock_send.return_value = True
            result = manager.send_survey(
                user_id="user_abc",
                user_email="user@test.com",
                product="localoutrank",
            )
        mock_send.assert_called_once()
        assert result["sent"] is True

    def test_record_score_saves_to_db(self, mock_db, cfg):
        manager = NpsManager(mock_db, cfg)
        with patch("agents.support.nps_manager.enqueue_sales_action") as mock_enqueue:
            result = manager.record(
                user_id="user_abc",
                product="localoutrank",
                score=8,
                comment="Pretty good",
            )
        mock_db.save_nps_response.assert_called_once()
        assert result["score"] == 8

    def test_detractor_enqueues_churn_recovery(self, mock_db, cfg):
        manager = NpsManager(mock_db, cfg)
        with patch("agents.support.nps_manager.enqueue_sales_action") as mock_enqueue:
            manager.record(
                user_id="user_abc",
                product="localoutrank",
                score=4,
                comment="Not happy",
            )
        mock_enqueue.assert_called_once_with(
            action="churn_recovery",
            user_id="user_abc",
            product="localoutrank",
        )

    def test_promoter_enqueues_referral_trigger(self, mock_db, cfg):
        manager = NpsManager(mock_db, cfg)
        with patch("agents.support.nps_manager.enqueue_sales_action") as mock_enqueue:
            manager.record(
                user_id="user_abc",
                product="localoutrank",
                score=10,
                comment="Love it!",
            )
        mock_enqueue.assert_called_once_with(
            action="referral_trigger",
            user_id="user_abc",
            product="localoutrank",
        )

    def test_passive_score_does_not_enqueue(self, mock_db, cfg):
        manager = NpsManager(mock_db, cfg)
        with patch("agents.support.nps_manager.enqueue_sales_action") as mock_enqueue:
            manager.record(
                user_id="user_abc",
                product="localoutrank",
                score=7,
                comment="It's ok",
            )
        mock_enqueue.assert_not_called()

    def test_score_boundary_exactly_6_is_detractor(self, mock_db, cfg):
        manager = NpsManager(mock_db, cfg)
        with patch("agents.support.nps_manager.enqueue_sales_action") as mock_enqueue:
            manager.record(user_id="u", product="localoutrank", score=6, comment="")
        mock_enqueue.assert_called_once()
        args = mock_enqueue.call_args
        assert args.kwargs["action"] == "churn_recovery"

    def test_score_boundary_exactly_9_is_promoter(self, mock_db, cfg):
        manager = NpsManager(mock_db, cfg)
        with patch("agents.support.nps_manager.enqueue_sales_action") as mock_enqueue:
            manager.record(user_id="u", product="localoutrank", score=9, comment="")
        mock_enqueue.assert_called_once()
        args = mock_enqueue.call_args
        assert args.kwargs["action"] == "referral_trigger"


# ---------------------------------------------------------------------------
# SupportAgent dispatch
# ---------------------------------------------------------------------------

class TestSupportAgent:

    @pytest.fixture
    def agent(self, cfg):
        from agents.support.main import SupportAgent
        config = MagicMock(spec=AgentConfig)
        config.custom = cfg
        config.llm_system_prompt = ""
        config.poll_interval_seconds = 2
        with patch("agents.support.main.SupportDB"), \
             patch("agents.support.main.TicketHandler"), \
             patch("agents.support.main.AutoResolver"), \
             patch("agents.support.main.KBManager"), \
             patch("agents.support.main.ProactiveMonitor"), \
             patch("agents.support.main.NpsManager"):
            return SupportAgent("support", config)

    def test_unknown_action_returns_error(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "fly_to_moon"},
        )
        result = agent.handle(task)
        assert result.success is False
        assert "error" in result.output

    def test_handle_ticket_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "handle_ticket",
                "product": "localoutrank",
                "user_id": "user_abc",
                "channel": "email",
                "subject": "Help",
                "body": "I need help",
                "user_email": "user@test.com",
            },
        )
        agent._ticket_handler.handle.return_value = {"ticket_id": "t1", "classification": "HOW_TO"}
        result = agent.handle(task)
        assert result.success is True
        agent._ticket_handler.handle.assert_called_once()

    def test_resolve_auto_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "resolve_auto",
                "auto_action": "password_reset",
                "user_id": "user_abc",
                "user_email": "user@test.com",
                "product": "localoutrank",
            },
        )
        agent._resolver.resolve.return_value = {"action": "password_reset", "success": True}
        result = agent.handle(task)
        assert result.success is True
        agent._resolver.resolve.assert_called_once()

    def test_kb_update_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "kb_update", "product": "localoutrank"},
        )
        agent._kb.update.return_value = {"articles_created": 3}
        result = agent.handle(task)
        assert result.success is True
        agent._kb.update.assert_called_once()

    def test_proactive_support_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "proactive_support", "product": "localoutrank"},
        )
        agent._monitor.check.return_value = {"spike_detected": False}
        result = agent.handle(task)
        assert result.success is True
        agent._monitor.check.assert_called_once()

    def test_nps_survey_send_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "nps_survey",
                "sub_action": "send",
                "user_id": "user_abc",
                "user_email": "user@test.com",
                "product": "localoutrank",
            },
        )
        agent._nps.send_survey.return_value = {"sent": True}
        result = agent.handle(task)
        assert result.success is True
        agent._nps.send_survey.assert_called_once()

    def test_nps_survey_record_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "nps_survey",
                "sub_action": "record",
                "user_id": "user_abc",
                "product": "localoutrank",
                "score": 9,
                "comment": "Great!",
            },
        )
        agent._nps.record.return_value = {"score": 9}
        result = agent.handle(task)
        assert result.success is True
        agent._nps.record.assert_called_once()

    def test_health_check_true_when_db_ok(self, agent):
        agent._db.list_resolved_tickets.return_value = []
        assert agent.health_check() is True

    def test_health_check_false_on_db_error(self, agent):
        agent._db.list_resolved_tickets.side_effect = Exception("db down")
        assert agent.health_check() is False
