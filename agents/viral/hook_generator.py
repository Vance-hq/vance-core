"""
Hook generator — 10 hook variants per request, scored on a 4-dimension rubric.

Rubric dimensions (each 0-10):
  specificity      — is there a concrete detail, number, or named thing?
  curiosity_gap    — does it promise something the reader doesn't know yet?
  emotional_charge — does it evoke urgency, surprise, or recognition?
  shareability     — would someone forward or repost this?

Overall score = mean of four dimensions. Output sorted descending by score.
"""

from __future__ import annotations

import json
import re
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

logger = get_logger(__name__)

_VALID_TONES = {"controversial", "educational", "personal_story", "data_driven"}

_HOOK_SYSTEM = """You are a content strategist who writes viral hooks.

Generate exactly 10 hook variants for the given topic, platform, and tone.
Each hook must be a single sentence or short phrase — the opening line of a post.

Output a JSON array of 10 strings. Return only valid JSON, no explanation.

Hook quality rules:
- Specificity: use a concrete number, date, company name, or named problem. Not "many businesses".
- Curiosity gap: make the reader feel they're missing something important.
- Emotional charge: urgency, surprise, validation, or mild provocation.
- No clickbait with no payoff. No "you won't believe" phrasing.
- No exclamation marks.
"""

_TONE_INSTRUCTIONS: dict[str, str] = {
    "controversial": "Take a direct, counter-narrative position. Challenge a widely-held assumption.",
    "educational": "Lead with a fact, statistic, or little-known truth that reframes a common problem.",
    "personal_story": "Open with a first-person moment — something that happened, went wrong, or surprised you.",
    "data_driven": "Lead with a specific number, percentage, or measurable finding.",
}

_SCORE_SYSTEM = """You are scoring hooks against a 4-dimension quality rubric.

For each hook in the provided JSON array, score it on:
  specificity      (0-10) — concrete detail, number, or named thing
  curiosity_gap    (0-10) — promises something the reader doesn't know
  emotional_charge (0-10) — urgency, surprise, or recognition
  shareability     (0-10) — would someone forward or repost this?

Output a JSON array where each object has:
  text             (string)
  specificity      (int)
  curiosity_gap    (int)
  emotional_charge (int)
  shareability     (int)
  score            (float — mean of four dimensions, rounded to 1 decimal)

Return only valid JSON, no explanation.
"""

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


class HookGenerator:

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg

    def generate(
        self,
        topic: str,
        platform: str,
        tone: str,
    ) -> dict[str, Any]:
        if tone not in _VALID_TONES:
            return {"error": f"tone must be one of: {', '.join(sorted(_VALID_TONES))}"}

        tone_instruction = _TONE_INSTRUCTIONS[tone]
        hooks_raw = self._generate_hooks(topic, platform, tone_instruction)
        hooks_list = self._parse_hooks_list(hooks_raw)
        scored = self._score_hooks(hooks_list)
        scored.sort(key=lambda h: h.get("score", 0), reverse=True)

        return {
            "topic": topic,
            "platform": platform,
            "tone": tone,
            "hooks": scored,
        }

    # ------------------------------------------------------------------

    def _generate_hooks(self, topic: str, platform: str, tone_instruction: str) -> str:
        prompt = (
            f"Topic: {topic}\n"
            f"Platform: {platform}\n"
            f"Tone instruction: {tone_instruction}\n\n"
            "Generate 10 hook variants."
        )
        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_HOOK_SYSTEM,
            max_tokens=600,
            metadata={"caller": "viral.hook_generator.generate"},
        ).content[0].text.strip()

    def _parse_hooks_list(self, raw: str) -> list[str]:
        try:
            match = _JSON_ARRAY_RE.search(raw)
            data = json.loads(match.group() if match else raw)
            if isinstance(data, list):
                hooks = [str(item) for item in data if item]
                return hooks[:10]
        except (json.JSONDecodeError, AttributeError):
            pass
        # Fallback: parse numbered list
        lines = [
            re.sub(r"^\d+[\.\)]\s*", "", line).strip()
            for line in raw.split("\n")
            if re.match(r"^\d+[\.\)]", line.strip())
        ]
        return lines[:10] if lines else [raw[:200]]

    def _score_hooks(self, hooks: list[str]) -> list[dict[str, Any]]:
        prompt = json.dumps(hooks)
        raw = llm.complete(
            messages=[{"role": "user", "content": f"Score these hooks:\n{prompt}"}],
            system=_SCORE_SYSTEM,
            max_tokens=800,
            metadata={"caller": "viral.hook_generator.score"},
        ).content[0].text.strip()

        try:
            match = _JSON_ARRAY_RE.search(raw)
            scored = json.loads(match.group() if match else raw)
            if isinstance(scored, list) and scored:
                # Ensure score field exists on each item
                result = []
                for item in scored:
                    if isinstance(item, dict):
                        dims = [
                            item.get("specificity", 5),
                            item.get("curiosity_gap", 5),
                            item.get("emotional_charge", 5),
                            item.get("shareability", 5),
                        ]
                        item["score"] = round(sum(dims) / len(dims), 1)
                        result.append(item)
                return result
        except (json.JSONDecodeError, AttributeError):
            logger.warning("hook_score_parse_failed", raw_preview=raw[:100])

        # Fallback: synthetic scores if LLM scoring fails
        return [
            {
                "text": h,
                "specificity": 5,
                "curiosity_gap": 5,
                "emotional_charge": 5,
                "shareability": 5,
                "score": 5.0,
            }
            for h in hooks
        ]
