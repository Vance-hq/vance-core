"""
StuckUserAlert — detect users who haven't logged in 5+ days post-signup.

Personal email from Dutch. Reply-to routes back to support agent.
"""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger

from .db import OnboardingDB
from .mailer import send_email

logger = get_logger(__name__)

_STUCK_HTML = """
<p>Hey,</p>
<p>You signed up for {product_name} a few days ago but I never heard from you — what happened?</p>
<p>Was it too complicated? Did something not work? Or just got busy?</p>
<p>Hit reply and tell me. I read every response personally.</p>
<p>— Dutch</p>
"""


class StuckUserAlert:

    def __init__(self, db: OnboardingDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def detect_and_alert(
        self,
        user_lookup: dict[str, str],
        days_inactive: int = 5,
    ) -> dict[str, Any]:
        stuck_users = self._db.get_stuck_users(days_inactive=days_inactive)
        alerted = 0

        for state in stuck_users:
            user_id = state.get("user_id", "")
            product = state.get("product", "")
            user_email = user_lookup.get(user_id)
            if not user_email:
                continue

            prod_cfg = self._cfg.get("products", {}).get(product, {})
            html = _STUCK_HTML.format(product_name=prod_cfg.get("name", product))

            sent = send_email(
                api_key=self._cfg.get("resend_api_key", ""),
                to=user_email,
                from_email=prod_cfg.get("from_email", self._cfg.get("dutch_email", "")),
                from_name=prod_cfg.get("from_name", "Dutch"),
                subject=f"You signed up for {prod_cfg.get('name', product)} — what happened?",
                html=html,
                reply_to=self._cfg.get("dutch_reply_to", self._cfg.get("dutch_email", "")),
            )
            if sent:
                alerted += 1
            logger.info("stuck_user_alerted", user_id=user_id, product=product, sent=sent)

        return {
            "stuck_count": len(stuck_users),
            "alerted": alerted,
        }
