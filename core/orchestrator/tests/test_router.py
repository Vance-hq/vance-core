"""Tests for the intent router."""

import pytest
from pathlib import Path
from unittest.mock import patch, mock_open
import yaml

from core.orchestrator.router import Router, RouteResult, UnknownIntentResult

_MINIMAL_CONFIG = {
    "intents": [
        {
            "agent": "analytics",
            "action": "revenue_report",
            "description": "Revenue",
            "priority": "NORMAL",
            "patterns": ["check revenue", "show mrr", "revenue numbers"],
            "fan_out": [],
        },
        {
            "agent": "dev",
            "action": "deploy",
            "description": "Deploy",
            "priority": "HIGH",
            "patterns": ["deploy", "ship it", "go live"],
            "fan_out": [{"agent": "security", "action": "check_uptime", "priority": "HIGH"}],
        },
        {
            "agent": "vance_system",
            "action": "unknown",
            "description": "Fallback",
            "priority": "NORMAL",
            "patterns": [],
        },
    ]
}


@pytest.fixture
def router(tmp_path):
    cfg = tmp_path / "routing_config.yaml"
    cfg.write_text(yaml.dump(_MINIMAL_CONFIG))
    return Router(config_path=cfg)


def test_structured_route_high_confidence(router):
    results = router.route(
        raw_text="pull our mrr",
        structured_agent="analytics",
        structured_action="revenue_report",
        confidence=0.92,
    )
    assert isinstance(results, list)
    assert results[0].agent == "analytics"
    assert results[0].action == "revenue_report"
    assert results[0].matched_via == "structured"


def test_fuzzy_route_on_low_confidence(router):
    results = router.route(
        raw_text="show me the revenue numbers",
        structured_agent="analytics",
        structured_action="revenue_report",
        confidence=0.4,  # below threshold
    )
    assert isinstance(results, list)
    assert results[0].agent == "analytics"
    assert results[0].matched_via == "fuzzy"


def test_unknown_intent_returns_unknown_result(router):
    result = router.route(
        raw_text="play some jazz music please",
        structured_agent="vance_system",
        structured_action="unknown",
        confidence=0.2,
    )
    assert isinstance(result, UnknownIntentResult)


def test_fan_out_included_in_results(router):
    results = router.route(
        raw_text="deploy this",
        structured_agent="dev",
        structured_action="deploy",
        confidence=0.9,
    )
    assert len(results) == 2
    agents = [r.agent for r in results]
    assert "dev" in agents
    assert "security" in agents


def test_priority_assignment(router):
    results = router.route(
        raw_text="ship it",
        structured_agent="dev",
        structured_action="deploy",
        confidence=0.9,
    )
    assert results[0].priority == 3  # HIGH


def test_reload_does_not_crash(router, tmp_path):
    cfg = tmp_path / "routing_config.yaml"
    cfg.write_text(yaml.dump(_MINIMAL_CONFIG))
    router.reload(cfg)
    assert len(router._entries) == len(_MINIMAL_CONFIG["intents"])
