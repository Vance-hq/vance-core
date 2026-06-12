"""Tests for the intent parser."""

import json
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def parser_config():
    return {
        "model": None,
        "confidence_threshold": 0.7,
        "max_context_turns": 5,
    }


@pytest.fixture
def mock_llm_response(text: str):
    """Helper: build a fake anthropic Message object."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def test_parse_high_confidence_intent(parser_config):
    llm_payload = json.dumps({
        "intent": "analytics.revenue_report",
        "agent": "analytics",
        "action": "revenue_report",
        "entities": {"product": "null"},
        "confidence": 0.92,
        "reasoning": "User asked for MRR.",
    })

    with patch("shared.llm.client.LLMClient") as mock_llm_cls:
        mock_llm = MagicMock()
        msg = MagicMock()
        msg.content = [MagicMock(text=llm_payload)]
        mock_llm.complete.return_value = msg
        mock_llm_cls.return_value = mock_llm

        from vance.core.voice.intent.parser import IntentParser
        from vance.core.voice.intent.intent_schema import IntentConfidence

        p = IntentParser(parser_config)
        p.llm = mock_llm
        intent = p.parse("what's our MRR?", [])

    assert intent.agent == "analytics"
    assert intent.action == "revenue_report"
    assert intent.confidence_level == IntentConfidence.HIGH
    assert intent.confidence == pytest.approx(0.92)


def test_parse_fallback_on_json_error(parser_config):
    with patch("shared.llm.client.LLMClient") as mock_llm_cls:
        mock_llm = MagicMock()
        msg = MagicMock()
        msg.content = [MagicMock(text="not valid json")]
        mock_llm.complete.return_value = msg
        mock_llm_cls.return_value = mock_llm

        from vance.core.voice.intent.parser import IntentParser
        from vance.core.voice.intent.intent_schema import IntentConfidence

        p = IntentParser(parser_config)
        p.llm = mock_llm
        intent = p.parse("garble garble", [])

    assert intent.agent == "vance_system"
    assert intent.action == "unknown"
    assert intent.confidence == 0.0
    assert intent.confidence_level == IntentConfidence.LOW
