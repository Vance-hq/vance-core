"""OpportunityEvaluator — scores opportunities from intel agent; auto-initiates research on high scores."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import StrategyDB

logger = get_logger(__name__)

_RESEARCH_THRESHOLD = 8.0

_SYSTEM = (
    "You are a strategic advisor to a SaaS founder evaluating a new opportunity. "
    "Score it on a 0-10 scale based on four factors: "
    "market size, competitive advantage, alignment with existing products, and effort required. "
    "Effort should be scored inversely (low effort = high score). "
    "Output JSON only:\n"
    "{\"score\": float, \"market_size\": \"large|medium|small\", "
    "\"competitive_advantage\": \"high|medium|low\", "
    "\"alignment\": \"high|medium|low\", "
    "\"effort\": \"low|medium|high\", "
    "\"rationale\": str}\n\n"
    "Score >= 8 means pursue immediately. Score < 8 means archive."
)


class OpportunityEvaluator:

    def __init__(self, db: StrategyDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def evaluate(self, opportunity: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            f"Opportunity: {opportunity.get('title', 'Untitled')}\n"
            f"Source: {opportunity.get('source', 'unknown')}\n"
            f"Description: {opportunity.get('description', '')}\n"
            f"Market size indicator: {opportunity.get('market_size', 'unknown')}"
        )

        try:
            resp = llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system=_SYSTEM,
                max_tokens=400,
            )
            raw = resp.content[0].text.strip()
            evaluation = json.loads(raw)
            score = float(evaluation.get("score", 0.0))
        except Exception as exc:
            logger.warning("opportunity_evaluator_llm_failed", error=str(exc))
            evaluation = {"score": 0.0, "rationale": "Evaluation failed — archived by default."}
            score = 0.0

        if score >= _RESEARCH_THRESHOLD:
            action_taken = self._initiate_research(opportunity=opportunity, evaluation=evaluation)
        else:
            action_taken = "archived"
            logger.info("opportunity_archived", title=opportunity.get("title"), score=score)

        return {**evaluation, "opportunity": opportunity, "action_taken": action_taken}

    def _initiate_research(self, opportunity: dict, evaluation: dict) -> str:
        queue = TaskQueue()
        try:
            queue.push(
                "research",
                {
                    "action": "deep_dive",
                    "topic": opportunity.get("title", ""),
                    "description": opportunity.get("description", ""),
                    "source": "opportunity_evaluator",
                    "score": evaluation.get("score"),
                    "rationale": evaluation.get("rationale", ""),
                },
            )
            logger.info("research_initiated", opportunity=opportunity.get("title"), score=evaluation.get("score"))
        except Exception as exc:
            logger.warning("opportunity_research_push_failed", error=str(exc))

        try:
            score = evaluation.get("score", 0)
            text = (
                f"High-value opportunity identified: {opportunity.get('title', '')}. "
                f"Score: {score:.1f} out of 10. "
                f"{evaluation.get('rationale', '')} "
                "Research deep dive has been initiated automatically."
            )
            queue.push(
                "voice",
                {
                    "action": "speak",
                    "text": text,
                    "priority": "high",
                    "source": "opportunity_evaluator",
                },
            )
        except Exception as exc:
            logger.warning("opportunity_voice_notify_failed", error=str(exc))

        return "research_initiated"
