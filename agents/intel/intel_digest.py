"""IntelDigest — compile daily intel into a brief pushed to reporting agent."""

from __future__ import annotations

from datetime import date
from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import IntelDB

logger = get_logger(__name__)


class IntelDigest:

    def __init__(self, db: IntelDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        today = date.today().isoformat()
        signals = self._db.list_signals(product=product, min_relevance=6, limit=20)
        trends = self._db.list_keyword_trends(product=product, direction="rising")

        digest_data = {
            "product": product,
            "date": today,
            "high_relevance_signals": signals[:5],
            "rising_keywords": [t["keyword"] for t in trends[:5]],
            "total_signals_today": len(signals),
        }

        try:
            TaskQueue().push(
                agent="reporting",
                payload={
                    "action": "add_to_brief",
                    "section": "intel",
                    "data": digest_data,
                    "source": "intel",
                },
            )
        except Exception as exc:
            logger.warning("intel_digest_enqueue_failed", error=str(exc))

        logger.info("intel_digest_compiled", product=product, signals=len(signals))
        return digest_data
