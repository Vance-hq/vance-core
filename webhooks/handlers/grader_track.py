"""
Click tracking and open pixel handlers for LocalRankGrader nurture emails.

open pixel:  GET /hooks/grader/open/{lead_id}/{step}.gif
click track: GET /hooks/grader/click/{lead_id}?to={url}&pricing=1
"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import unquote_plus

from shared.logger import get_logger

logger = get_logger(__name__)

# 1×1 transparent GIF
_PIXEL_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


def handle_open_event(lead_id: str, step: int) -> bytes:
    """Record email open, return tracking pixel GIF bytes."""
    try:
        from agents.localrankgrader.db import GraderDB
        db = GraderDB()
        db.record_email_event(lead_id, "open", step, 0)
        logger.info("grader_open_tracked", lead_id=lead_id, step=step)
    except Exception as exc:
        logger.warning("grader_open_track_failed", error=str(exc))
    return _PIXEL_GIF


def handle_click_event(lead_id: str, to_url: str, pricing: bool = False) -> dict[str, Any]:
    """
    Record link click, update lead score.
    Returns redirect target URL.
    """
    delta = 40 if pricing else 20
    event_type = "pricing_visit" if pricing else "click"
    new_score = 0
    try:
        from agents.localrankgrader.db import GraderDB
        from agents.localrankgrader.nurture import NurtureSequencer
        from agents._base.config import AgentConfig

        db = GraderDB()
        db.record_email_event(lead_id, event_type, None, delta)
        new_score = db.add_score(lead_id, delta)

        config = AgentConfig.load("local_rank_grader")
        threshold = config.custom.get("upgrade_nudge_threshold", 80)
        from agents.localrankgrader.email import GraderMailer
        sequencer = NurtureSequencer(db, GraderMailer(), upgrade_nudge_threshold=threshold)
        sequencer.handle_score_update(lead_id, new_score)

        logger.info("grader_click_tracked", lead_id=lead_id, pricing=pricing, new_score=new_score)
    except Exception as exc:
        logger.warning("grader_click_track_failed", error=str(exc))

    destination = unquote_plus(to_url)
    return {"redirect_to": destination, "score": new_score}
