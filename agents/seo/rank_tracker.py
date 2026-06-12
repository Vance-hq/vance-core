"""
Rank tracker — weekly keyword ranking snapshots via SerpAPI.

Stores weekly position data in Postgres.
Alerts the reporting agent when a top-10 keyword drops >= 3 positions.
"""

from __future__ import annotations

from typing import Any

import httpx

from shared.logger import get_logger

from .db import SeoDB

logger = get_logger(__name__)


def alert_reporting_agent(
    product: str,
    keyword: str,
    previous_rank: int,
    current_rank: int,
    drop: int,
) -> None:
    """Fire a rank-drop alert task to the reporting agent."""
    from shared.queue.queue import TaskQueue
    from shared.types import AgentCapability, Task
    import uuid
    try:
        queue = TaskQueue()
        queue.push(Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.ANALYTICS,
            payload={
                "action": "rank_drop_alert",
                "product": product,
                "keyword": keyword,
                "previous_rank": previous_rank,
                "current_rank": current_rank,
                "drop": drop,
            },
        ))
        logger.warning(
            "rank_drop_alert_fired",
            product=product,
            keyword=keyword,
            previous=previous_rank,
            current=current_rank,
            drop=drop,
        )
    except Exception as exc:
        logger.warning("rank_alert_enqueue_failed", keyword=keyword, error=str(exc))


class RankTracker:

    def __init__(self, db: SeoDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._serp_api_key = cfg.get("serp_api_key", "")
        self._drop_threshold = int(cfg.get("rank_drop_threshold", 3))

    def track(
        self,
        product: str,
        keywords: list[str],
    ) -> dict[str, Any]:
        product_cfg = self._cfg.get("products", {}).get(product, {})
        domain = product_cfg.get("domain", "")
        snapshot: list[dict[str, Any]] = []

        for keyword in keywords:
            rank, ranking_url = self._fetch_rank(keyword, domain)
            prev_rows = self._db.get_previous_rankings(product=product, keyword=keyword, limit=1)
            previous_rank = prev_rows[0]["rank"] if prev_rows else None

            self._db.save_keyword_ranking(
                product=product,
                keyword=keyword,
                rank=rank,
                url=ranking_url or f"https://{domain}",
            )

            # Alert only for top-10 drops >= threshold
            if (
                previous_rank is not None
                and previous_rank <= 10
                and rank > previous_rank
                and (rank - previous_rank) >= self._drop_threshold
            ):
                alert_reporting_agent(
                    product=product,
                    keyword=keyword,
                    previous_rank=previous_rank,
                    current_rank=rank,
                    drop=rank - previous_rank,
                )

            snapshot.append({
                "keyword": keyword,
                "rank": rank,
                "previous_rank": previous_rank,
                "url": ranking_url,
                "change": (rank - previous_rank) if previous_rank else None,
            })

        logger.info("rank_tracking_complete", product=product, keywords=len(keywords))

        return {
            "product": product,
            "keywords_tracked": len(keywords),
            "snapshot": snapshot,
        }

    # ------------------------------------------------------------------

    def _fetch_rank(self, keyword: str, domain: str) -> tuple[int, str]:
        """Query SerpAPI and find our domain's position. Returns (rank, url)."""
        if not self._serp_api_key:
            return 0, ""
        try:
            resp = httpx.get(
                "https://serpapi.com/search",
                params={
                    "q": keyword,
                    "api_key": self._serp_api_key,
                    "engine": "google",
                    "num": 100,
                },
                timeout=20,
            )
            if resp.status_code != 200:
                return 0, ""

            results = resp.json().get("organic_results", [])
            for result in results:
                link = result.get("link", "")
                if domain and domain in link:
                    return int(result.get("position", 0)), link

            # If domain not in results at all, return a rank beyond tracked range
            return 101, ""

        except Exception as exc:
            logger.warning("serp_rank_fetch_failed", keyword=keyword, error=str(exc))
            return 0, ""
