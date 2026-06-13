"""PerformanceTracker — pull video analytics and surface insights."""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import VideoDB

logger = get_logger(__name__)

_LOW_CTR_THRESHOLD = 0.02    # < 2% CTR is poor
_LOW_VIEW_THRESHOLD = 0.30   # < 30% avg view duration is poor


def _fetch_youtube_stats(video_id: str, api_key: str) -> dict[str, Any]:
    try:
        import httpx
        resp = httpx.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "statistics,contentDetails",
                "id": video_id,
                "key": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return {}
        stats = items[0].get("statistics", {})
        return {
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
        }
    except Exception as exc:
        logger.warning("youtube_fetch_failed", video_id=video_id, error=str(exc))
        return {}


class PerformanceTracker:

    def __init__(self, db: VideoDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, video_ids: list[str], platform: str = "youtube") -> dict[str, Any]:
        api_key = self._cfg.get("youtube_api_key", "")
        results = []

        for vid in video_ids:
            stats = _fetch_youtube_stats(video_id=vid, api_key=api_key) if platform == "youtube" else {}
            views = stats.get("views", 0)

            self._db.upsert_performance(
                video_id=vid,
                platform=platform,
                title=stats.get("title", vid),
                views=views,
                watch_time_h=stats.get("watch_time_h", 0.0),
                ctr=stats.get("ctr"),
                avg_view_pct=stats.get("avg_view_pct"),
            )

            insights = []
            if stats.get("ctr") and float(stats["ctr"]) < _LOW_CTR_THRESHOLD:
                insights.append("low_ctr — consider A/B testing the thumbnail and title")
            if stats.get("avg_view_pct") and float(stats["avg_view_pct"]) < _LOW_VIEW_THRESHOLD * 100:
                insights.append("low_retention — hook may need rework")

            results.append({"video_id": vid, "views": views, "insights": insights})

        if results:
            self._notify_reporting(results)

        logger.info("video_performance_tracked", videos=len(video_ids))
        return {"platform": platform, "videos_tracked": len(video_ids), "results": results}

    def _notify_reporting(self, results: list[dict]) -> None:
        try:
            TaskQueue().push(
                agent="reporting",
                payload={
                    "action": "add_to_brief",
                    "section": "video",
                    "data": {"video_performance": results},
                    "source": "video",
                },
            )
        except Exception as exc:
            logger.warning("notify_reporting_failed", error=str(exc))
