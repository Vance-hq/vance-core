"""Celery tasks for the video agent — weekly performance tracking."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.video.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    pass


@app.task(name="agents.video.tasks.weekly_performance_check", ignore_result=True)
def weekly_performance_check() -> None:
    """Run weekly — pull video performance from YouTube for all tracked videos."""
    import uuid

    from agents._base import AgentConfig
    from agents.video.main import VideoAgent
    from shared.types import AgentCapability, Task

    config = AgentConfig.load("video")
    agent = VideoAgent("video", config)
    video_ids = config.custom.get("tracked_video_ids", [])
    if not video_ids:
        return

    task = Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.VIDEO,
        payload={"action": "track_performance", "video_ids": video_ids},
    )
    try:
        agent.handle(task)
    except Exception as exc:
        logger.error("weekly_performance_check_failed", error=str(exc))
