"""
Intent router — maps a VoiceIntent to one or more RouteResult objects.

Strategy:
  1. If the VoiceIntent carries a structured intent with confidence >= threshold
     AND it is not 'vance_system.unknown', trust the LLM parse directly.
  2. Otherwise fall back to fuzzy pattern matching on raw_text using rapidfuzz.

Adding a new agent/action only requires entries in routing_config.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz, process

from shared.logger import get_logger

logger = get_logger(__name__)

_ROUTING_CONFIG = Path(__file__).parent / "routing_config.yaml"

PRIORITY_MAP: dict[str, int] = {
    "CRITICAL": 1,
    "HIGH": 3,
    "NORMAL": 5,
    "LOW": 8,
}

# Minimum fuzzy score (0-100) to accept a pattern match
_FUZZY_THRESHOLD = 65


@dataclass
class RouteResult:
    agent: str
    action: str
    priority: int
    matched_via: str          # "structured" | "fuzzy" | "fan_out"
    pattern_matched: str | None = None
    fuzzy_score: float | None = None
    fan_out: list["RouteResult"] = field(default_factory=list)


@dataclass
class UnknownIntentResult:
    raw_text: str
    best_score: float
    best_pattern: str | None


class Router:
    """Config-driven intent router with fuzzy fallback."""

    def __init__(self, config_path: Path = _ROUTING_CONFIG) -> None:
        self._entries: list[dict[str, Any]] = []
        # Flat lookup: (agent, action) → entry
        self._index: dict[tuple[str, str], dict[str, Any]] = {}
        # Flat list for fuzzy matching: [(pattern_text, (agent, action)), ...]
        self._patterns: list[tuple[str, tuple[str, str]]] = []

        self._load(config_path)

    def _load(self, path: Path) -> None:
        with open(path) as f:
            config = yaml.safe_load(f)

        for entry in config.get("intents", []):
            agent = entry["agent"]
            action = entry["action"]
            key = (agent, action)
            self._entries.append(entry)
            self._index[key] = entry

            for pattern in entry.get("patterns", []):
                self._patterns.append((pattern, key))

        logger.info(
            "router_loaded",
            entries=len(self._entries),
            patterns=len(self._patterns),
        )

    def reload(self, config_path: Path = _ROUTING_CONFIG) -> None:
        """Hot-reload routing config without restarting."""
        self._entries.clear()
        self._index.clear()
        self._patterns.clear()
        self._load(config_path)
        logger.info("router_reloaded")

    def route(
        self,
        raw_text: str,
        structured_agent: str | None = None,
        structured_action: str | None = None,
        confidence: float = 0.0,
        confidence_threshold: float = 0.70,
    ) -> list[RouteResult] | UnknownIntentResult:
        """
        Route a command to one or more agents.

        Args:
            raw_text:            Original transcribed text.
            structured_agent:    Agent parsed by LLM (from VoiceIntent.agent).
            structured_action:   Action parsed by LLM (from VoiceIntent.action).
            confidence:          LLM confidence score.
            confidence_threshold: Minimum confidence to trust the LLM parse.

        Returns:
            List of RouteResult (may include fan-out routes), or UnknownIntentResult.
        """
        # Path 1: trust the structured parse
        is_unknown = (
            structured_agent == "vance_system" and structured_action == "unknown"
        )
        if (
            structured_agent
            and structured_action
            and confidence >= confidence_threshold
            and not is_unknown
        ):
            key = (structured_agent, structured_action)
            entry = self._index.get(key)
            if entry:
                logger.debug(
                    "route_structured", agent=structured_agent, action=structured_action
                )
                return self._build_results(entry, via="structured")

        # Path 2: fuzzy match on raw_text
        return self._fuzzy_route(raw_text)

    def _fuzzy_route(
        self, raw_text: str
    ) -> list[RouteResult] | UnknownIntentResult:
        if not self._patterns:
            return UnknownIntentResult(raw_text=raw_text, best_score=0.0, best_pattern=None)

        pattern_texts = [p for p, _ in self._patterns]
        results = process.extract(
            raw_text.lower(),
            pattern_texts,
            scorer=fuzz.partial_ratio,
            limit=5,
        )

        if not results or results[0][1] < _FUZZY_THRESHOLD:
            best = results[0] if results else None
            logger.info(
                "route_unknown",
                raw_text=raw_text,
                best_score=best[1] if best else 0,
                best_pattern=best[0] if best else None,
            )
            return UnknownIntentResult(
                raw_text=raw_text,
                best_score=best[1] if best else 0.0,
                best_pattern=best[0] if best else None,
            )

        # Map back to (agent, action) via position index
        matched_pattern = results[0][0]
        score = results[0][1]
        matched_key: tuple[str, str] | None = None
        for pattern, key in self._patterns:
            if pattern == matched_pattern:
                matched_key = key
                break

        if matched_key is None:
            return UnknownIntentResult(raw_text=raw_text, best_score=score, best_pattern=matched_pattern)

        entry = self._index[matched_key]
        logger.info(
            "route_fuzzy",
            agent=matched_key[0],
            action=matched_key[1],
            pattern=matched_pattern,
            score=score,
        )
        return self._build_results(entry, via="fuzzy", pattern=matched_pattern, score=score)

    def _build_results(
        self,
        entry: dict[str, Any],
        via: str,
        pattern: str | None = None,
        score: float | None = None,
    ) -> list[RouteResult]:
        priority = PRIORITY_MAP.get(entry.get("priority", "NORMAL"), 5)

        fan_out: list[RouteResult] = []
        for fo in entry.get("fan_out", []):
            fo_priority = PRIORITY_MAP.get(fo.get("priority", "NORMAL"), 5)
            fan_out.append(
                RouteResult(
                    agent=fo["agent"],
                    action=fo["action"],
                    priority=fo_priority,
                    matched_via="fan_out",
                )
            )

        primary = RouteResult(
            agent=entry["agent"],
            action=entry["action"],
            priority=priority,
            matched_via=via,
            pattern_matched=pattern,
            fuzzy_score=score,
            fan_out=fan_out,
        )

        # Flatten: primary + all fan-out routes as a single dispatch list
        return [primary] + fan_out
