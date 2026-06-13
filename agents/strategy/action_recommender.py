"""ActionRecommender — generates 3 prioritized recommendations; auto-executes high-confidence ones."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import StrategyDB

logger = get_logger(__name__)

_DEFAULT_THRESHOLD = 0.8

_SYSTEM = (
    "You are a strategic advisor to a SaaS founder. "
    "Given recent signals and insights, generate exactly 3 prioritized recommendations. "
    "Each recommendation must include: which agent should execute it, the specific action, and a confidence score. "
    "Output JSON array only:\n"
    "[{\"recommendation\": str, \"rationale\": str, \"agent_target\": str, "
    "\"action\": str, \"confidence\": float (0-1), \"expected_outcome\": str}]\n\n"
    "Order by confidence descending. Be specific and actionable. "
    "agent_target must be one of: marketing, sales, ads, content, seo, outreach, research, analytics."
)


class ActionRecommender:

    def __init__(self, db: StrategyDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._threshold = float(cfg.get("auto_execute_threshold", _DEFAULT_THRESHOLD))

    def recommend(self, products: list[str]) -> dict[str, Any]:
        signals: list[dict] = []
        for product in products:
            signals.extend(self._db.list_signals(product=product, actioned=False, limit=10))

        recent_insights = self._db.get_recent_insights(limit=5)

        signal_lines = [f"- [{s['signal_type']}] {s['summary']}" for s in signals]
        insight_lines = [f"- {i['insight']} (confidence: {i['confidence']:.0%})" for i in recent_insights]

        prompt = (
            f"Products: {', '.join(products)}\n\n"
            f"Recent signals:\n" + ("\n".join(signal_lines) or "None") + "\n\n"
            f"Strategic insights:\n" + ("\n".join(insight_lines) or "None")
        )

        try:
            resp = llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system=_SYSTEM,
                max_tokens=900,
            )
            raw = resp.content[0].text.strip()
            recs = json.loads(raw)
            if not isinstance(recs, list):
                raise ValueError("Expected JSON array")
        except Exception as exc:
            logger.warning("action_recommender_llm_failed", error=str(exc))
            return {"recommendations": [], "auto_executed": 0, "pending_approval": 0}

        auto_executed = 0
        pending_approval = 0
        queue = TaskQueue()

        for rec in recs:
            confidence = float(rec.get("confidence", 0.0))
            rec_id = self._db.save_recommendation(
                recommendation=rec.get("recommendation", ""),
                rationale=rec.get("rationale", ""),
                agent_target=rec.get("agent_target", ""),
                confidence=confidence,
            )

            if confidence >= self._threshold:
                self._auto_execute(queue=queue, rec=rec, rec_id=rec_id)
                auto_executed += 1
            else:
                self._request_approval(queue=queue, rec=rec)
                pending_approval += 1

        logger.info(
            "recommendations_generated",
            total=len(recs),
            auto_executed=auto_executed,
            pending_approval=pending_approval,
        )
        return {
            "recommendations": recs,
            "auto_executed": auto_executed,
            "pending_approval": pending_approval,
        }

    def _auto_execute(self, queue: Any, rec: dict, rec_id: str) -> None:
        try:
            agent_target = rec.get("agent_target", "")
            queue.push(
                agent_target,
                {
                    "action": rec.get("action", ""),
                    "recommendation": rec.get("recommendation", ""),
                    "rationale": rec.get("rationale", ""),
                    "source": "strategy_auto_execute",
                },
            )
            self._db.mark_recommendation_executed(rec_id)
            logger.info("recommendation_auto_executed", agent=agent_target, rec_id=rec_id)
        except Exception as exc:
            logger.warning("recommendation_auto_execute_failed", error=str(exc))

    def _request_approval(self, queue: Any, rec: dict) -> None:
        try:
            text = (
                f"Recommendation for your approval: {rec.get('recommendation', '')}. "
                f"Rationale: {rec.get('rationale', '')}. "
                f"Expected outcome: {rec.get('expected_outcome', '')}. "
                "Reply yes to execute."
            )
            queue.push(
                "voice",
                {
                    "action": "speak",
                    "text": text,
                    "priority": "normal",
                    "source": "action_recommender",
                    "requires_approval": True,
                    "agent_target": rec.get("agent_target", ""),
                    "action_to_execute": rec.get("action", ""),
                },
            )
        except Exception as exc:
            logger.warning("recommendation_approval_request_failed", error=str(exc))
