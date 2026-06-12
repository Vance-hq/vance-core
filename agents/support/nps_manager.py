"""
NPS manager — send surveys and route responses.

Flow:
  1. send_survey()  — triggered 30 days after signup or first meaningful action
  2. record()       — score stored in DB; detractors → churn_recovery,
                      promoters → referral_trigger
"""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger

from .db import SupportDB
from .mailer import send_email

logger = get_logger(__name__)

_NPS_EMAIL_HTML = """
<p>Hi,</p>
<p>On a scale of 0–10, <strong>how likely are you to recommend {product_name} to a colleague?</strong></p>
<p>
  {score_links}
</p>
<p>— {from_name}</p>
"""

_SCORE_LINK = '<a href="{base_url}?score={n}&uid={user_id}" style="margin: 0 4px; padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; text-decoration: none;">{n}</a>'


def enqueue_sales_action(
    action: str,
    user_id: str,
    product: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="sales",
            payload={
                "action": action,
                "user_id": user_id,
                "product": product,
                "source": "nps",
            },
        )
    except Exception as exc:
        logger.warning("nps_enqueue_failed", action=action, user_id=user_id, error=str(exc))


class NpsManager:

    def __init__(self, db: SupportDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def send_survey(
        self,
        user_id: str,
        user_email: str,
        product: str,
    ) -> dict[str, Any]:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        product_name = prod_cfg.get("name", product)
        from_email = self._cfg.get("nps_from_email", prod_cfg.get("support_email", "nps@vance.com"))
        from_name = prod_cfg.get("from_name", product_name)
        nps_base_url = f"https://{product}.com/nps"

        score_links = " ".join(
            _SCORE_LINK.format(base_url=nps_base_url, n=n, user_id=user_id)
            for n in range(11)
        )
        html = _NPS_EMAIL_HTML.format(
            product_name=product_name,
            score_links=score_links,
            from_name=from_name,
        )

        sent = send_email(
            api_key=self._cfg.get("resend_api_key", ""),
            to=user_email,
            from_email=from_email,
            from_name=from_name,
            subject=f"Quick question about {product_name} (30 seconds)",
            html=html,
        )

        logger.info("nps_survey_sent", user_id=user_id, product=product, sent=sent)
        return {"sent": sent, "user_id": user_id, "product": product}

    def record(
        self,
        user_id: str,
        product: str,
        score: int,
        comment: str = "",
    ) -> dict[str, Any]:
        response_id = self._db.save_nps_response(
            user_id=user_id,
            product=product,
            score=score,
            comment=comment,
        )

        if score <= 6:
            enqueue_sales_action(
                action="churn_recovery",
                user_id=user_id,
                product=product,
            )
        elif score >= 9:
            enqueue_sales_action(
                action="referral_trigger",
                user_id=user_id,
                product=product,
            )

        logger.info("nps_recorded", user_id=user_id, product=product, score=score)
        return {
            "response_id": response_id,
            "user_id": user_id,
            "product": product,
            "score": score,
        }
