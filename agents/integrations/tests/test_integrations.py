"""Integration Agent unit tests — no live HTTP, DB, or Redis."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from agents.integrations.audit_log import AuditLog
from agents.integrations.registry import get_connector, list_services
from agents.integrations.agent import IntegrationAgent


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

def test_get_connector_all_18():
    expected = {
        "github", "vercel", "cloudflare", "railway", "supabase",
        "stripe", "square", "quickbooks", "google_workspace",
        "google_analytics", "google_ads", "google_business_profile",
        "meta_ads", "slack", "twilio", "calendly", "twenty_crm", "backblaze",
    }
    assert set(list_services()) == expected


def test_get_connector_unknown_raises():
    with pytest.raises(ValueError, match="Unknown service"):
        get_connector("nonexistent_service")


def test_get_connector_returns_class():
    cls = get_connector("github")
    assert cls.service_name == "github"


# ------------------------------------------------------------------
# AuditLog — silent on DB failure
# ------------------------------------------------------------------

def test_audit_log_swallows_db_errors():
    audit = AuditLog()
    with patch("agents.integrations.audit_log.get_db", side_effect=Exception("db down")):
        # must not raise
        audit.log(
            service="test",
            method="test_method",
            endpoint="/test",
            status_code=200,
            latency_ms=10,
        )


# ------------------------------------------------------------------
# BaseConnector — rate limiting
# ------------------------------------------------------------------

def _make_connector(service: str = "github"):
    cls = get_connector(service)
    with patch("redis.Redis"):
        inst = cls.__new__(cls)
        inst._task_id = "test-task"
        inst._called_by = "test"
        inst._method_name = "test_method"
        inst._audit = MagicMock()
        inst._redis = MagicMock()
        return inst


def test_rate_limit_allows_under_limit():
    conn = _make_connector("github")
    conn._redis.incr.return_value = 1
    conn._redis.ttl.return_value = 60
    # Should not raise
    conn.rate_limit(100, 60)


def test_rate_limit_raises_over_limit():
    from agents.integrations.connectors.base_connector import BaseConnector
    conn = _make_connector("github")
    conn._redis.incr.return_value = 101
    conn._redis.ttl.return_value = 45
    with pytest.raises(RuntimeError, match="rate limit"):
        conn.rate_limit(100, 60)


# ------------------------------------------------------------------
# IntegrationAgent dispatch
# ------------------------------------------------------------------

def _make_task(service: str, method: str, args: dict | None = None) -> MagicMock:
    task = MagicMock()
    task.id = "task-001"
    task.payload = {
        "action": "call_service",
        "service": service,
        "method": method,
        "args": args or {},
    }
    return task


def test_agent_list_services():
    agent = MagicMock(spec=IntegrationAgent)
    agent.handle = IntegrationAgent.handle.__get__(agent)
    task = MagicMock()
    task.id = "t-001"
    task.payload = {"action": "list_services"}
    result = agent.handle(task)
    assert "services" in result.output
    assert len(result.output["services"]) == 18


def test_agent_unknown_action_raises():
    agent = MagicMock(spec=IntegrationAgent)
    agent.handle = IntegrationAgent.handle.__get__(agent)
    task = MagicMock()
    task.id = "t-002"
    task.payload = {"action": "do_something_fake"}
    with pytest.raises(ValueError, match="Unknown integrations action"):
        agent.handle(task)


def test_agent_unknown_service_raises():
    agent = MagicMock(spec=IntegrationAgent)
    agent.agent_name = "integrations"
    agent.handle = IntegrationAgent.handle.__get__(agent)
    agent._call_service = IntegrationAgent._call_service.__get__(agent)
    task = _make_task("unknown_service_xyz", "some_method")
    with pytest.raises(ValueError, match="Unknown service"):
        agent.handle(task)


def test_agent_unknown_method_raises():
    agent = MagicMock(spec=IntegrationAgent)
    agent.agent_name = "integrations"
    agent.handle = IntegrationAgent.handle.__get__(agent)
    agent._call_service = IntegrationAgent._call_service.__get__(agent)

    task = _make_task("slack", "nonexistent_method_xyz")
    with patch("agents.integrations.agent.get_connector") as mock_get:
        mock_cls = MagicMock()
        mock_instance = MagicMock()
        del mock_instance.nonexistent_method_xyz  # ensure getattr returns None
        mock_instance.__class__.__name__ = "SlackConnector"
        type(mock_instance).nonexistent_method_xyz = None
        mock_get.return_value = mock_cls
        mock_cls.return_value = mock_instance
        with pytest.raises(ValueError, match="has no method"):
            agent.handle(task)


# ------------------------------------------------------------------
# Connector credential loaders (just ensure they don't raise without env vars)
# ------------------------------------------------------------------

@pytest.mark.parametrize("service", [
    "github", "vercel", "cloudflare", "railway", "supabase",
    "stripe", "square", "quickbooks", "google_workspace",
    "google_analytics", "google_ads", "google_business_profile",
    "meta_ads", "slack", "twilio", "calendly", "twenty_crm",
])
def test_load_credentials_returns_dict(service: str):
    cls = get_connector(service)
    creds = cls.load_credentials()
    assert isinstance(creds, dict)


def test_backblaze_load_credentials_empty():
    cls = get_connector("backblaze")
    assert cls.load_credentials() == {}
