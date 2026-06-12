"""
Remix engine — weekly task that takes top-performing viral pieces and
repurposes them for other platforms.

A LinkedIn hot-take → Twitter thread + TikTok script.
A Twitter thread → LinkedIn post + Facebook post.
A TikTok script → LinkedIn post + Twitter thread.

Remixed pieces are enqueued to the content calendar via the content agent task queue.
"""

from __future__ import annotations

from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import ViralDB

logger = get_logger(__name__)

# Which platforms to remix into, given the source platform
_REMIX_TARGETS: dict[str, list[str]] = {
    "twitter":   ["linkedin", "tiktok"],
    "linkedin":  ["twitter", "tiktok"],
    "tiktok":    ["linkedin", "twitter"],
    "facebook":  ["twitter", "linkedin"],
}

_REMIX_SYSTEM = """You are Dutch — a contractor who built software. Remix this content for a new platform.

Adapt the core idea and any specific data/story — don't just copy-paste.
Each platform needs its own format and voice:
  twitter   → thread, hook tweet + 4-6 supporting tweets, separated by ---
  linkedin  → 800-1200 chars, insight-forward, ends with question or POV
  tiktok    → short video script: HOOK (3s) / 3 beats (10-15s each) / CTA (5s)
  facebook  → conversational, 200-400 chars, ends with engagement question

Return only the remixed content — no labels, no explanation.
"""


def enqueue_content_task(product: str, platform: str, topic: str, body: str) -> None:
    """Enqueue remixed content to the content calendar via Celery."""
    from agents.content.tasks import schedule_content_entry
    import uuid
    try:
        from datetime import date, datetime, timedelta, timezone
        # Schedule 2 days out to avoid flooding
        eta_date = date.today() + timedelta(days=2)
        eta_dt = datetime(eta_date.year, eta_date.month, eta_date.day, 9, 0, tzinfo=timezone.utc)
        schedule_content_entry.apply_async(
            kwargs={
                "entry_id": str(uuid.uuid4()),
                "entry": {
                    "product": product,
                    "platform": platform,
                    "type": "social_post",
                    "topic": topic,
                    "date": str(eta_date),
                    "_remix_body": body,
                },
            },
            eta=eta_dt,
        )
    except Exception as exc:
        logger.warning("remix_enqueue_failed", product=product, platform=platform, error=str(exc))


class RemixEngine:

    def __init__(self, db: ViralDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def remix(self, product: str) -> dict[str, Any]:
        top_pieces = self._db.get_top_pieces(product=product, days=30, limit=5)

        if not top_pieces:
            return {"remixed": 0, "product": product}

        total_remixed = 0

        for piece in top_pieces:
            source_platform = piece.get("platform", "twitter")
            targets = _REMIX_TARGETS.get(source_platform, ["twitter", "linkedin"])
            original = piece.get("content", "") or piece.get("hook", "")
            hook = piece.get("hook", "")

            for target_platform in targets:
                remixed_body = self._remix_piece(
                    original=original,
                    hook=hook,
                    source_platform=source_platform,
                    target_platform=target_platform,
                    product=product,
                )
                topic = f"Remix: {hook[:60]}..." if len(hook) > 60 else hook
                enqueue_content_task(
                    product=product,
                    platform=target_platform,
                    topic=topic,
                    body=remixed_body,
                )
                total_remixed += 1

        logger.info("remix_complete", product=product, remixed=total_remixed)
        return {"remixed": total_remixed, "product": product, "source_pieces": len(top_pieces)}

    # ------------------------------------------------------------------

    def _remix_piece(
        self,
        original: str,
        hook: str,
        source_platform: str,
        target_platform: str,
        product: str,
    ) -> str:
        prompt = (
            f"Product: {product}\n"
            f"Original platform: {source_platform}\n"
            f"Target platform: {target_platform}\n"
            f"Original hook: {hook}\n\n"
            f"Original content:\n{original[:800]}\n\n"
            f"Remix this for {target_platform}."
        )
        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_REMIX_SYSTEM,
            max_tokens=600,
            metadata={"caller": f"viral.remix_engine.{target_platform}"},
        ).content[0].text.strip()
