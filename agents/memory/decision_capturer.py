"""Decision capturer — records significant decisions and outcomes to decision_log."""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger

from .embedder import embed

logger = get_logger(__name__)


class DecisionCapturer:

    def __init__(self, db: Any, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def capture(
        self,
        agent: str,
        action: str,
        intent: str,
        outcome: str,
        product: str = "",
    ) -> dict[str, Any]:
        embedding = embed(f"{intent} {outcome}")
        decision_id = self._db.save_decision(
            agent=agent,
            action=action,
            intent=intent,
            outcome=outcome,
            product=product,
            embedding=embedding,
        )
        logger.info("decision_captured", decision_id=decision_id, agent=agent, action=action)
        return {
            "decision_id": decision_id,
            "agent": agent,
            "action": action,
            "product": product,
            "has_embedding": embedding is not None,
        }
