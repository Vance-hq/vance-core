"""
ProductHuntLaunch — full PH launch orchestration.

Generates all five copy pieces, schedules support social posts,
notifies Dutch so he can post at the right window.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import LaunchDB

logger = get_logger(__name__)

_PH_SYSTEM = (
    "You are a Product Hunt launch specialist. Write high-converting copy for a PH launch. "
    "Reply with JSON only: "
    "{\"tagline\": str (max 60 chars), \"description\": str (max 260 chars), "
    "\"maker_comment\": str (personal, 150-300 chars), "
    "\"first_comment\": str (quick-start guide, 150-250 chars), "
    "\"hunter_message\": str (outreach template with [name] placeholder, 100-150 chars)}. "
    "Tagline must be under 60 characters. Be specific to the product — no generic copy."
)

_PH_SOCIAL_TIMES = ["06:00", "09:00", "12:00", "15:00", "18:00"]


def enqueue_social_posts(
    product: str,
    launch_date: date,
    tagline: str,
    product_url: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        for t in _PH_SOCIAL_TIMES:
            TaskQueue().push(
                agent="content",
                payload={
                    "action": "publish_social",
                    "product": product,
                    "platform": "all",
                    "scheduled_time": f"{launch_date.isoformat()}T{t}:00Z",
                    "content": f"🚀 We're live on Product Hunt today! {tagline}\n{product_url}",
                },
                priority=8,
            )
    except Exception as exc:
        logger.warning("enqueue_ph_social_failed", product=product, error=str(exc))


def send_ph_notification(
    product: str,
    launch_date: date,
    tagline: str,
    notify_email: str,
    api_key: str,
) -> None:
    import httpx
    try:
        httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": f"Launch Bot <launches@vance.com>",
                "to": [notify_email],
                "subject": f"[ACTION] {product} PH launch is today — post at 12:01am PST",
                "html": (
                    f"<p>Your Product Hunt launch for <strong>{product}</strong> "
                    f"is scheduled for <strong>{launch_date}</strong>.</p>"
                    f"<p>Tagline: <em>{tagline}</em></p>"
                    f"<p>Post at 12:01am PST for maximum upvote window.</p>"
                ),
            },
            timeout=15,
        )
    except Exception as exc:
        logger.warning("ph_notification_failed", product=product, error=str(exc))


class ProductHuntLaunch:

    def __init__(self, db: LaunchDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def orchestrate(
        self,
        product: str,
        launch_date: date,
    ) -> dict[str, Any]:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        product_name = prod_cfg.get("name", product)
        product_url = prod_cfg.get("url", f"https://{product}.com")

        prompt = (
            f"Product: {product_name}\n"
            f"URL: {product_url}\n"
            f"Launch date: {launch_date}\n"
            "Write all Product Hunt launch copy."
        )

        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_PH_SYSTEM,
            max_tokens=1024,
        )
        raw = resp.content[0].text.strip()

        try:
            copy = json.loads(raw)
        except json.JSONDecodeError:
            copy = {
                "tagline": f"{product_name} — built for results",
                "description": raw[:260],
                "maker_comment": "",
                "first_comment": "",
                "hunter_message": "",
            }

        # Enforce 60-char tagline limit
        tagline = copy.get("tagline", "")[:60]

        enqueue_social_posts(
            product=product,
            launch_date=launch_date,
            tagline=tagline,
            product_url=product_url,
        )

        send_ph_notification(
            product=product,
            launch_date=launch_date,
            tagline=tagline,
            notify_email=self._cfg.get("ph_notify_email", self._cfg.get("dutch_email", "")),
            api_key=self._cfg.get("resend_api_key", ""),
        )

        logger.info("ph_launch_orchestrated", product=product, launch_date=str(launch_date))
        return {
            "product": product,
            "launch_date": launch_date.isoformat(),
            "tagline": tagline,
            "description": copy.get("description", "")[:260],
            "maker_comment": copy.get("maker_comment", ""),
            "first_comment": copy.get("first_comment", ""),
            "hunter_message": copy.get("hunter_message", ""),
            "social_posts_queued": True,
        }
