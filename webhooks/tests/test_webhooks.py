"""Webhook service tests — auth middleware, Mailcow handler, Stripe routing."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from webhooks.app import app

client = TestClient(app, raise_server_exceptions=False)

VALID_SECRET = "test-hook-secret-abc123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings():
    """Return the Settings singleton via sys.modules (avoids __init__ shadowing)."""
    return sys.modules["shared.config.settings"].settings


@contextmanager
def _db_mock(fetchone_result=None):
    """Yield a mock psycopg2 connection with a cursor that returns fetchone_result."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = fetchone_result
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    yield mock_conn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_secrets():
    """Patch the Settings singleton so tests don't need real secrets."""
    s = _settings()
    original_hook = s.VANCE_HOOK_SECRET
    original_stripe = s.STRIPE_WEBHOOK_SECRET
    s.VANCE_HOOK_SECRET = VALID_SECRET
    s.STRIPE_WEBHOOK_SECRET = "whsec_test"
    yield
    s.VANCE_HOOK_SECRET = original_hook
    s.STRIPE_WEBHOOK_SECRET = original_stripe


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

class TestAuth:
    def test_missing_secret_returns_401(self):
        r = client.post("/hooks/mailcow/reply", json={})
        assert r.status_code == 401

    def test_wrong_secret_returns_401(self):
        r = client.post(
            "/hooks/mailcow/reply",
            json={},
            headers={"X-Vance-Hook-Secret": "wrong-secret"},
        )
        assert r.status_code == 401

    def test_401_does_not_reveal_secret_value(self):
        r = client.post("/hooks/mailcow/reply", json={})
        body = r.text
        assert VALID_SECRET not in body
        assert "wrong" not in body.lower() or "invalid" not in body.lower()

    def test_generic_hook_requires_secret(self):
        r = client.post("/hooks/generic/test", json={"x": 1})
        assert r.status_code == 401

    def test_stripe_endpoint_bypasses_shared_secret(self):
        # Stripe uses its own HMAC — no X-Vance-Hook-Secret.
        # Invalid Stripe sig → 400, not 401.
        r = client.post(
            "/hooks/stripe/event",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=bad"},
        )
        assert r.status_code == 400

    def test_valid_secret_passes_auth(self):
        with (
            patch("webhooks.handlers.mailcow_reply.get_db") as mock_db,
            patch("webhooks.handlers.mailcow_reply._classify_with_llm", return_value=("NOT_INTERESTED", 0.9)),
            patch("webhooks.handlers.mailcow_reply._log_classification"),
        ):
            mock_db.return_value = _db_mock(fetchone_result=None)
            r = client.post(
                "/hooks/mailcow/reply",
                json={"from_email": "x@y.com", "to_email": "a@b.com", "subject": "Re: Hi", "body": "I'll pass."},
                headers={"X-Vance-Hook-Secret": VALID_SECRET},
            )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Mailcow reply — classification routing
# ---------------------------------------------------------------------------

class TestMailcowReply:
    def _post(self, payload: dict) -> MagicMock:
        return client.post(
            "/hooks/mailcow/reply",
            json=payload,
            headers={"X-Vance-Hook-Secret": VALID_SECRET},
        )

    def test_interested_reply_enqueues_high_priority_outreach_task(self):
        with (
            patch("webhooks.handlers.mailcow_reply.get_db") as mock_db,
            patch("webhooks.handlers.mailcow_reply._classify_with_llm", return_value=("INTERESTED", 0.95)),
            patch("webhooks.handlers.mailcow_reply._log_classification"),
            patch("webhooks.handlers.mailcow_reply._queue") as mock_q,
        ):
            mock_db.return_value = _db_mock(fetchone_result=None)
            mock_q.push.return_value = "task-xyz"

            r = self._post({
                "from_email": "lead@example.com",
                "to_email": "outreach@vance.com",
                "subject": "Re: Quick question",
                "body": "Yes, I'm interested — tell me more.",
                "original_message_id": "<abc@mail.vance.com>",
            })

        assert r.status_code == 200
        assert r.json()["category"] == "INTERESTED"
        mock_q.push.assert_called_once()
        call_kw = mock_q.push.call_args.kwargs
        assert call_kw["agent"] == "outreach"
        assert call_kw["priority"] == 3  # HIGH

    def test_question_reply_also_enqueues_outreach(self):
        with (
            patch("webhooks.handlers.mailcow_reply.get_db") as mock_db,
            patch("webhooks.handlers.mailcow_reply._classify_with_llm", return_value=("QUESTION", 0.88)),
            patch("webhooks.handlers.mailcow_reply._log_classification"),
            patch("webhooks.handlers.mailcow_reply._queue") as mock_q,
        ):
            mock_db.return_value = _db_mock()
            mock_q.push.return_value = "task-q"

            r = self._post({
                "from_email": "curious@example.com",
                "to_email": "a@b.com",
                "subject": "Re: Hi",
                "body": "How much does it cost?",
            })

        assert r.status_code == 200
        assert r.json()["category"] == "QUESTION"
        mock_q.push.assert_called_once()

    def test_unsubscribe_keyword_skips_llm(self):
        with (
            patch("webhooks.handlers.mailcow_reply.get_db") as mock_db,
            patch("webhooks.handlers.mailcow_reply._classify_with_llm") as mock_llm,
            patch("webhooks.handlers.mailcow_reply._mark_unsubscribed") as mock_unsub,
            patch("webhooks.handlers.mailcow_reply._log_classification"),
            patch("webhooks.handlers.mailcow_reply._queue") as mock_q,
        ):
            mock_db.return_value = _db_mock()

            r = self._post({
                "from_email": "tired@example.com",
                "to_email": "a@b.com",
                "subject": "Unsubscribe me please",
                "body": "Please remove me from your list.",
            })

        assert r.status_code == 200
        assert r.json()["category"] == "UNSUBSCRIBE"
        mock_llm.assert_not_called()
        mock_unsub.assert_called_once_with("tired@example.com")
        mock_q.push.assert_not_called()

    def test_not_interested_does_not_enqueue(self):
        with (
            patch("webhooks.handlers.mailcow_reply.get_db") as mock_db,
            patch("webhooks.handlers.mailcow_reply._classify_with_llm", return_value=("NOT_INTERESTED", 0.88)),
            patch("webhooks.handlers.mailcow_reply._log_classification"),
            patch("webhooks.handlers.mailcow_reply._queue") as mock_q,
        ):
            mock_db.return_value = _db_mock()

            r = self._post({
                "from_email": "cold@example.com",
                "to_email": "a@b.com",
                "subject": "Re: Outreach",
                "body": "Not interested, thanks.",
            })

        assert r.status_code == 200
        assert r.json()["category"] == "NOT_INTERESTED"
        mock_q.push.assert_not_called()

    @pytest.mark.parametrize("body,subject", [
        ("opt out", ""),
        ("please remove me from your list", ""),
        ("stop emailing me", ""),
        ("", "unsubscribe"),
    ])
    def test_unsubscribe_keyword_variants(self, body, subject):
        with (
            patch("webhooks.handlers.mailcow_reply.get_db") as mock_db,
            patch("webhooks.handlers.mailcow_reply._classify_with_llm") as mock_llm,
            patch("webhooks.handlers.mailcow_reply._mark_unsubscribed"),
            patch("webhooks.handlers.mailcow_reply._log_classification"),
            patch("webhooks.handlers.mailcow_reply._queue"),
        ):
            mock_db.return_value = _db_mock()
            r = self._post({"from_email": "x@y.com", "to_email": "a@b.com", "subject": subject, "body": body})

        assert r.json()["category"] == "UNSUBSCRIBE"
        mock_llm.assert_not_called()


# ---------------------------------------------------------------------------
# LLM classification parser
# ---------------------------------------------------------------------------

class TestClassifyWithLLM:
    def _mock_llm(self, text: str) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text=text)]
        return mock_resp

    def test_parses_valid_json(self):
        from webhooks.handlers.mailcow_reply import _classify_with_llm

        with patch("webhooks.handlers.mailcow_reply.llm.complete",
                   return_value=self._mock_llm('{"category": "INTERESTED", "confidence": 0.92}')):
            category, confidence = _classify_with_llm("Re: Question", "Love to learn more!")

        assert category == "INTERESTED"
        assert confidence == pytest.approx(0.92)

    def test_strips_markdown_fences(self):
        from webhooks.handlers.mailcow_reply import _classify_with_llm

        with patch("webhooks.handlers.mailcow_reply.llm.complete",
                   return_value=self._mock_llm(
                       '```json\n{"category": "QUESTION", "confidence": 0.75}\n```'
                   )):
            category, confidence = _classify_with_llm("?", "Can you tell me more?")

        assert category == "QUESTION"
        assert confidence == pytest.approx(0.75)

    def test_handles_malformed_response_gracefully(self):
        from webhooks.handlers.mailcow_reply import _classify_with_llm

        with patch("webhooks.handlers.mailcow_reply.llm.complete",
                   return_value=self._mock_llm("Sorry, cannot classify.")):
            category, confidence = _classify_with_llm("bad", "bad")

        assert category == "NOT_INTERESTED"
        assert confidence == 0.0

    def test_invalid_category_falls_back(self):
        from webhooks.handlers.mailcow_reply import _classify_with_llm

        with patch("webhooks.handlers.mailcow_reply.llm.complete",
                   return_value=self._mock_llm('{"category": "MAYBE", "confidence": 0.5}')):
            category, _ = _classify_with_llm("x", "x")

        assert category == "NOT_INTERESTED"


# ---------------------------------------------------------------------------
# Generic hook
# ---------------------------------------------------------------------------

def test_generic_hook_accepted_with_valid_secret():
    r = client.post(
        "/hooks/generic/zapier",
        json={"event": "form_submitted", "data": {}},
        headers={"X-Vance-Hook-Secret": VALID_SECRET},
    )
    assert r.status_code == 200
    assert r.json()["source"] == "zapier"
