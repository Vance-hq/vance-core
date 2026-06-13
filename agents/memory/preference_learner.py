"""Preference learner — infers Dutch's behavioral preferences from decision log patterns."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from shared.llm.client import llm
from shared.logger import get_logger

logger = get_logger(__name__)

_ANALYSIS_SYSTEM = (
    "You are a behavioral analyst studying patterns in an operator's decisions. "
    "Analyze the decision log and infer reusable preferences about how work should be done. "
    "Focus on: copy style, campaign timing, agent overrides, CTA types, subject line length, approval patterns. "
    'Return a JSON array: [{"key": "preference_name", "value": "specific_preference", '
    '"confidence": 0.0-1.0, "evidence": "one sentence evidence"}]. '
    "Only include confidence > 0.6. Max 10 preferences."
)


class PreferenceLearner:

    def __init__(self, db: Any, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def learn(self, days: int = 30) -> dict[str, Any]:
        decisions = self._db.list_recent_decisions(days=days, limit=50)
        if not decisions:
            return {"preferences_updated": 0, "preferences": []}

        lines = [
            f"- [{d.get('product', '?')}] {d['agent']}.{d['action']}: "
            f"intent={d.get('intent', '')} outcome={d.get('outcome', '')}"
            for d in decisions
        ]
        decisions_text = "\n".join(lines)

        try:
            resp = llm.complete(
                messages=[{"role": "user", "content": f"Decision log (last {days} days):\n{decisions_text}"}],
                system=_ANALYSIS_SYSTEM,
                max_tokens=600,
            )
            raw = resp.content[0].text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            inferred = json.loads(raw)
            if not isinstance(inferred, list):
                inferred = []
        except Exception as exc:
            logger.warning("preference_learning_failed", error=str(exc))
            return {"preferences_updated": 0, "preferences": [], "error": str(exc)}

        updated_keys: list[str] = []
        for pref in inferred:
            key = pref.get("key", "")
            value = pref.get("value", "")
            if not key or not value:
                continue
            self._db.upsert_preference(
                key=key,
                value=value,
                confidence=float(pref.get("confidence", 0.5)),
                source_evidence=pref.get("evidence", ""),
            )
            updated_keys.append(key)

        # Persist all learned preferences to yaml so agents can load them
        all_prefs = self._db.list_preferences()
        self._write_preferences_yaml(all_prefs)

        logger.info("preferences_learned", count=len(updated_keys))
        return {"preferences_updated": len(updated_keys), "preferences": updated_keys}

    def _write_preferences_yaml(self, preferences: list[dict[str, Any]]) -> None:
        prefs_file = self._cfg.get("preferences_file", "agents/memory/preferences.yaml")
        prefs_path = Path(prefs_file)
        prefs_path.parent.mkdir(parents=True, exist_ok=True)

        prefs_dict = {p["key"]: {"value": p["value"], "confidence": p["confidence"]} for p in preferences}
        try:
            with open(prefs_path, "w") as f:
                yaml.dump(prefs_dict, f, default_flow_style=False, allow_unicode=True)
        except Exception as exc:
            logger.warning("preferences_yaml_write_failed", path=str(prefs_path), error=str(exc))
