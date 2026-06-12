"""
Intent parser — converts raw transcribed text into a structured VoiceIntent.
Uses Claude via shared/llm/client.py. The LLM is given:
  1. The transcribed text
  2. The full list of available agent actions (loaded from routing_config.yaml)
  3. Session context (last N turns)
It returns structured JSON which is validated into a VoiceIntent object.
"""

import json
import logging
import sys
import uuid
from pathlib import Path

import yaml
from pydantic import ValidationError

from .intent_schema import IntentConfidence, VoiceIntent

# Resolve the vance/ project root regardless of where Python is invoked from
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared.llm.client import LLMClient  # noqa: E402

logger = logging.getLogger(__name__)

INTENT_SYSTEM_PROMPT = """
You are the intent parser for Vance, an autonomous AI system controlled by Dutch Munn.
Dutch is a serial entrepreneur managing multiple software products and a plumbing business.

Your job: convert Dutch's voice command into a structured JSON object.

You will be given:
1. The transcribed voice command (raw_text)
2. A list of available agents and their actions
3. Recent conversation context

Return ONLY a valid JSON object with this exact schema:
{
  "intent": "agent.action",
  "agent": "agent_name",
  "action": "action_name",
  "entities": {
    "product": "starpio|oneserv|localoutrank|trusted_plumbing|vance_system|null",
    "any_other_param": "value"
  },
  "confidence": 0.0 to 1.0,
  "reasoning": "one sentence explaining your interpretation"
}

RULES:
- intent must exactly match one of the available agent.action combinations
- If the command is ambiguous between two intents, pick the most likely one and lower confidence
- If no intent matches at all: agent="vance_system", action="unknown", confidence=0.3
- Extract all relevant entities mentioned (product names, numbers, dates, names, campaign IDs)
- Product detection:
  "starpio", "star", "review platform" → starpio
  "oneserv", "field service", "the FSM" → oneserv
  "grader", "rank grader", "local rank", "localoutrank" → localoutrank
  "trusted", "the plumbing business", "TP" → trusted_plumbing
- Return ONLY the JSON object. No explanation, no markdown, no preamble.
""".strip()


class IntentParser:
    def __init__(self, config: dict):
        self.config = config
        self.llm = LLMClient()
        self.confidence_threshold = config["confidence_threshold"]
        self.max_context_turns = config["max_context_turns"]

        routing_config_path = (
            Path(__file__).resolve().parents[4]
            / "core"
            / "orchestrator"
            / "routing_config.yaml"
        )
        if routing_config_path.exists():
            with open(routing_config_path) as f:
                routing = yaml.safe_load(f)
            self.available_actions = self._build_action_list(routing)
        else:
            logger.warning(
                "routing_config.yaml not found — intent parser will have limited accuracy"
            )
            self.available_actions = []

    def _build_action_list(self, routing: dict) -> list[str]:
        actions = []
        for entry in routing.get("intents", []):
            agent = entry.get("agent", "")
            action = entry.get("action", "")
            if agent and action:
                actions.append(f"{agent}.{action}")
        return list(set(actions))

    def parse(self, raw_text: str, session_context: list[dict]) -> VoiceIntent:
        """
        Parse transcribed text into a VoiceIntent.

        Args:
            raw_text: transcribed voice command
            session_context: last N turns [{raw_text, intent, outcome}]

        Returns:
            VoiceIntent object
        """
        session_id = str(uuid.uuid4())

        user_prompt = (
            f'Voice command: "{raw_text}"\n\n'
            f"Available agent actions:\n"
            + "\n".join(self.available_actions)
            + f"\n\nRecent context (last {len(session_context)} turns):\n"
            + json.dumps(
                session_context[-self.max_context_turns :], indent=2, default=str
            )
            + "\n\nParse this command into the required JSON format."
        )

        response_text = ""
        try:
            response = self.llm.complete(
                messages=[{"role": "user", "content": user_prompt}],
                system=INTENT_SYSTEM_PROMPT,
                max_tokens=400,
                metadata={"caller": "intent_parser"},
            )
            response_text = response.content[0].text.strip()

            parsed = json.loads(response_text)

            confidence = float(parsed.get("confidence", 0.5))
            if confidence >= 0.85:
                confidence_level = IntentConfidence.HIGH
            elif confidence >= 0.70:
                confidence_level = IntentConfidence.MEDIUM
            else:
                confidence_level = IntentConfidence.LOW

            entities = parsed.get("entities", {})
            product = entities.pop("product", None)
            if product in (None, "null"):
                product = None

            intent = VoiceIntent(
                raw_text=raw_text,
                intent=parsed["intent"],
                agent=parsed["agent"],
                action=parsed["action"],
                entities=entities,
                product=product,
                confidence=confidence,
                confidence_level=confidence_level,
                session_context=session_context[-self.max_context_turns :],
                session_id=session_id,
            )

            logger.info(
                f"Intent parsed: {intent.intent} "
                f"(confidence: {confidence:.2f}, product: {product})"
            )
            return intent

        except (json.JSONDecodeError, KeyError, ValidationError) as e:
            logger.error(f"Intent parsing failed: {e}. Raw response: {response_text}")
            return VoiceIntent(
                raw_text=raw_text,
                intent="vance_system.unknown",
                agent="vance_system",
                action="unknown",
                entities={"parse_error": str(e)},
                product=None,
                confidence=0.0,
                confidence_level=IntentConfidence.LOW,
                session_context=session_context,
                session_id=session_id,
            )
