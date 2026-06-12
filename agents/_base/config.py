"""Agent configuration loaded from agents/{agent_name}/config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    agent_name: str
    enabled: bool = True
    poll_interval_seconds: float = 2.0
    max_retries: int = 3
    llm_system_prompt: str = ""
    custom: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def load(cls, agent_name: str) -> AgentConfig:
        path = Path(__file__).parent.parent / agent_name / "config.yaml"
        raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
        return cls(agent_name=agent_name, **raw)
