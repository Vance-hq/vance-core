"""
VoiceIntent — the output of the intent parser and the input to the orchestrator.
This is the single data contract between the voice layer and everything else.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IntentConfidence(str, Enum):
    HIGH = "high"       # >= 0.85 — execute immediately
    MEDIUM = "medium"   # 0.70-0.84 — execute with confirmation in response
    LOW = "low"         # < 0.70 — ask for clarification before executing


class VoiceIntent(BaseModel):
    # Raw input
    raw_text: str = Field(..., description="Exact transcribed text from STT")

    # Parsed intent
    intent: str = Field(
        ..., description="Normalized intent identifier, e.g. 'marketing.send_campaign'"
    )
    agent: str = Field(..., description="Target agent name, e.g. 'marketing'")
    action: str = Field(
        ..., description="Specific action on that agent, e.g. 'send_campaign'"
    )

    # Entities extracted from the utterance
    entities: dict = Field(
        default_factory=dict,
        description="Key params extracted: product, campaign_id, date, count, etc.",
    )

    # Product context
    product: Optional[str] = Field(
        None,
        description=(
            "Which product this relates to: "
            "starpio|oneserv|localoutrank|trusted_plumbing|vance_system"
        ),
    )

    # Confidence
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_level: IntentConfidence

    # Context
    session_context: list[dict] = Field(
        default_factory=list,
        description="Last N turns of conversation for context",
    )

    # Meta
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    session_id: str = Field(..., description="UUID for the current voice session")
