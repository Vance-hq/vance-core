"""KeywordTracker — monitor keyword volume trends, notify on significant movement."""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import IntelDB

logger = get_logger(__name__)

_MOVEMENT_THRESHOLD = 0.20  # 20% volume change = significant


def _get_keyword_volume(keyword: str) -> int:
    """Fetch search volume index from SearXNG or return 0 on failure."""
    try:
        from shared.search import search as _search
        results = _search(keyword, num_results=1)
        return len(results) * 100  # proxy: result count × 100
    except Exception:
        return 0


class KeywordTracker:

    def __init__(self, db: IntelDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        keywords = self._cfg.get("products", {}).get(product, {}).get("keywords", [])
        if not keywords:
            return {"product": product, "keywords_tracked": 0}

        prior = {r["keyword"]: r for r in self._db.list_keyword_trends(product=product)}
        movements = []

        for kw in keywords:
            current_vol = _get_keyword_volume(kw)
            prior_entry = prior.get(kw, {})
            prior_vol = prior_entry.get("volume_index", 0)

            direction = "stable"
            if prior_vol > 0:
                change = (current_vol - prior_vol) / prior_vol
                if change >= _MOVEMENT_THRESHOLD:
                    direction = "rising"
                elif change <= -_MOVEMENT_THRESHOLD:
                    direction = "falling"

            self._db.upsert_keyword_trend(
                keyword=kw, product=product, trend_direction=direction, volume_index=current_vol
            )

            if direction in ("rising", "falling"):
                movements.append({"keyword": kw, "direction": direction, "volume": current_vol})

        if movements:
            self._notify_movements(product=product, movements=movements)

        logger.info("keyword_tracking_complete", product=product, keywords=len(keywords), movements=len(movements))
        return {"product": product, "keywords_tracked": len(keywords), "significant_movements": movements}

    def _notify_movements(self, product: str, movements: list[dict]) -> None:
        try:
            TaskQueue().push(
                agent="reporting",
                payload={
                    "action": "add_to_brief",
                    "section": "intel",
                    "data": {"product": product, "keyword_movements": movements},
                    "source": "intel",
                },
            )
        except Exception as exc:
            logger.warning("notify_movements_failed", error=str(exc))
