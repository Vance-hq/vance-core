"""Placeholder tests for the marketing agent."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_health_endpoint():
    # TODO: spin up agent, hit /health, assert 200
    pass


@pytest.mark.asyncio
async def test_generate_copy_raises_not_implemented():
    # TODO: assert NotImplementedError until implementation lands
    pass


@pytest.mark.asyncio
async def test_unknown_action_raises():
    # TODO: assert ValueError on unknown action
    pass
