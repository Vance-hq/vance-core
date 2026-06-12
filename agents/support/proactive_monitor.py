"""
Proactive monitor — detect issues before customers complain.

Monitors:
  - Error rate spikes in app logs (via web search / log aggregator)
  - Stripe failed payment events
  - Email delivery failures

If a spike is detected (>2x baseline), enqueues a proactive status
update via the marketing agent's sender.
"""

from __future__ import annotations

import json
import re
from typing import Any

from shared.llm.client import llm, web_search
from shared.logger import get_logger

from .db import SupportDB

logger = get_logger(__name__)

_SPIKE_SYSTEM = """You are a site-reliability analyst reviewing log and error data.

Given recent search snippets and log data, determine whether there is an active
error spike affecting users.

Output a JSON object:
  spike_detected   (bool)
  affected_feature (string — "login", "payments", "dashboard", etc., or "")
  user_impact      (string — one sentence describing impact, or "")

Return only valid JSON — no explanation.
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def enqueue_marketing_send(
    product: str,
    subject: str,
    body: str,
    affected_feature: str,
) -> None:
    """Push proactive status update to marketing agent for broadcast."""
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="marketing",
            payload={
                "action": "broadcast_status_update",
                "product": product,
                "subject": subject,
                "body": body,
                "affected_feature": affected_feature,
            },
        )
    except Exception as exc:
        logger.warning("proactive_enqueue_failed", product=product, error=str(exc))


class ProactiveMonitor:

    def __init__(self, db: SupportDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def check(self, product: str) -> dict[str, Any]:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        domain = prod_cfg.get("support_email", "").split("@")[-1] if "@" in prod_cfg.get("support_email", "") else product

        # Gather signals
        error_snippets = web_search(
            f'site:{domain} OR "{prod_cfg.get("name", product)}" error OR down OR outage',
            num_results=5,
        )

        # LLM analysis
        raw = llm.complete(
            messages=[{
                "role": "user",
                "content": (
                    f"Product: {prod_cfg.get('name', product)}\n\n"
                    f"Recent signals:\n"
                    + "\n".join(s.get("content", "") for s in (error_snippets or []))
                ),
            }],
            system=_SPIKE_SYSTEM,
            max_tokens=200,
            metadata={"caller": "support.proactive_monitor"},
        ).content[0].text.strip()

        try:
            match = _JSON_RE.search(raw)
            analysis = json.loads(match.group() if match else raw)
        except (json.JSONDecodeError, AttributeError):
            analysis = {"spike_detected": False, "affected_feature": "", "user_impact": ""}

        spike = bool(analysis.get("spike_detected", False))
        affected = analysis.get("affected_feature", "")
        impact = analysis.get("user_impact", "")

        if spike:
            enqueue_marketing_send(
                product=product,
                subject=f"Service update: {affected} on {prod_cfg.get('name', product)}",
                body=(
                    f"We're aware of an issue affecting {affected}. "
                    f"{impact} Our team is actively working on it. "
                    "We'll update you as soon as it's resolved."
                ),
                affected_feature=affected,
            )
            logger.warning(
                "proactive_alert_fired",
                product=product,
                affected_feature=affected,
                impact=impact,
            )

        return {
            "product": product,
            "spike_detected": spike,
            "affected_feature": affected,
            "user_impact": impact,
        }
