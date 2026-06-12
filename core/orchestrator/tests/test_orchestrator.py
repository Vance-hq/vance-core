"""Tests for the orchestrator dispatch logic."""

import pytest
from unittest.mock import MagicMock, patch

from shared.types import AgentCapability, IntentResult


@pytest.mark.asyncio
async def test_dispatch_skips_low_confidence():
    intent = IntentResult(
        raw="do something",
        agent=AgentCapability.MARKETING,
        action="generate_copy",
        confidence=0.3,
    )
    # TODO: assert dispatch returns None for low-confidence intents
    pass


@pytest.mark.asyncio
async def test_dispatch_queues_high_confidence():
    intent = IntentResult(
        raw="write copy for Starpio landing page",
        agent=AgentCapability.MARKETING,
        action="generate_copy",
        confidence=0.9,
    )
    # TODO: assert task_id is returned and task is on the queue
    pass
