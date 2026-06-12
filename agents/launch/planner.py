"""
LaunchPlanner — builds a timestamped launch execution plan.

Generates a canonical task list per launch_type, optionally augmented
by LLM for product-specific additions. Stores plan to Postgres.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import LaunchDB

logger = get_logger(__name__)

# Canonical task templates per launch_type.
# offset_days: negative = before launch, 0 = launch day, positive = after.
_TASK_TEMPLATES: dict[str, list[dict]] = {
    "major_feature": [
        {"offset_days": -14, "agent": "content",   "action": "write_blog",         "critical": False},
        {"offset_days":  -7, "agent": "outreach",  "action": "early_access_email", "critical": True},
        {"offset_days":  -3, "agent": "video",     "action": "launch_video",       "critical": False},
        {"offset_days":  -1, "agent": "content",   "action": "queue_social",       "critical": False},
        {"offset_days":   0, "agent": "content",   "action": "publish_all",        "critical": True},
        {"offset_days":   0, "agent": "marketing", "action": "launch_email",       "critical": True},
        {"offset_days":   0, "agent": "dev",       "action": "flip_feature_flag",  "critical": True},
        {"offset_days":   1, "agent": "support",   "action": "proactive_faq",      "critical": False},
        {"offset_days":   7, "agent": "analytics", "action": "launch_report",      "critical": False},
    ],
    "new_product": [
        {"offset_days": -30, "agent": "content",   "action": "teaser_blog",          "critical": False},
        {"offset_days": -21, "agent": "outreach",  "action": "waitlist_email",       "critical": True},
        {"offset_days": -14, "agent": "ads",       "action": "pre_launch_ads",       "critical": False},
        {"offset_days":  -7, "agent": "outreach",  "action": "early_access_email",   "critical": True},
        {"offset_days":  -3, "agent": "video",     "action": "launch_video",         "critical": False},
        {"offset_days":  -1, "agent": "content",   "action": "queue_social",         "critical": False},
        {"offset_days":   0, "agent": "content",   "action": "publish_all",          "critical": True},
        {"offset_days":   0, "agent": "marketing", "action": "launch_email",         "critical": True},
        {"offset_days":   0, "agent": "dev",       "action": "flip_feature_flag",    "critical": True},
        {"offset_days":   1, "agent": "support",   "action": "proactive_faq",        "critical": False},
        {"offset_days":   3, "agent": "outreach",  "action": "follow_up_sequence",   "critical": False},
        {"offset_days":   7, "agent": "analytics", "action": "launch_report",        "critical": False},
    ],
    "price_change": [
        {"offset_days": -14, "agent": "content",   "action": "pricing_blog",         "critical": False},
        {"offset_days":  -7, "agent": "marketing", "action": "grandfathering_email", "critical": True},
        {"offset_days":  -3, "agent": "marketing", "action": "final_reminder",       "critical": True},
        {"offset_days":   0, "agent": "marketing", "action": "launch_email",         "critical": True},
        {"offset_days":   0, "agent": "dev",       "action": "flip_feature_flag",    "critical": True},
        {"offset_days":   1, "agent": "support",   "action": "proactive_faq",        "critical": False},
        {"offset_days":   7, "agent": "analytics", "action": "launch_report",        "critical": False},
    ],
    "rebrand": [
        {"offset_days": -21, "agent": "content",   "action": "teaser_blog",         "critical": False},
        {"offset_days": -14, "agent": "outreach",  "action": "early_access_email",  "critical": False},
        {"offset_days":  -7, "agent": "content",   "action": "rebrand_announcement","critical": False},
        {"offset_days":  -1, "agent": "content",   "action": "queue_social",        "critical": False},
        {"offset_days":   0, "agent": "content",   "action": "publish_all",         "critical": True},
        {"offset_days":   0, "agent": "marketing", "action": "launch_email",        "critical": True},
        {"offset_days":   0, "agent": "dev",       "action": "flip_feature_flag",   "critical": False},
        {"offset_days":   1, "agent": "support",   "action": "proactive_faq",       "critical": False},
        {"offset_days":   7, "agent": "analytics", "action": "launch_report",       "critical": False},
    ],
}

_PLANNER_SYSTEM = (
    "You are a product launch coordinator. Given a launch type and product, "
    "suggest any ADDITIONAL tasks not already covered by the base plan. "
    "Reply with JSON array of task objects: "
    "[{\"offset_days\": int, \"agent\": str, \"action\": str, \"critical\": bool}]. "
    "Return [] if no additions are needed. Keep it short — only genuinely necessary additions."
)


class LaunchPlanner:

    def __init__(self, db: LaunchDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def plan(
        self,
        product: str,
        launch_type: str,
        launch_date: date,
    ) -> dict[str, Any]:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        product_name = prod_cfg.get("name", product)

        base_tasks = [
            {**t, "status": "pending", "payload": {}}
            for t in _TASK_TEMPLATES.get(launch_type, _TASK_TEMPLATES["major_feature"])
        ]

        try:
            resp = llm.complete(
                messages=[{"role": "user", "content": (
                    f"Product: {product_name}\n"
                    f"Launch type: {launch_type}\n"
                    f"Launch date: {launch_date}\n"
                    f"Base plan agents: {list({t['agent'] for t in base_tasks})}\n"
                    "Suggest additional tasks if needed."
                )}],
                system=_PLANNER_SYSTEM,
                max_tokens=512,
            )
            import json
            extras = json.loads(resp.content[0].text.strip())
            if isinstance(extras, list):
                for extra in extras:
                    if all(k in extra for k in ("offset_days", "agent", "action")):
                        base_tasks.append({**extra, "status": "pending", "payload": {}})
        except Exception as exc:
            logger.warning("planner_llm_extras_failed", product=product, error=str(exc))

        plan_id = self._db.save_plan(
            product=product,
            launch_type=launch_type,
            launch_date=launch_date,
            tasks=base_tasks,
        )

        logger.info("launch_plan_created", plan_id=plan_id, product=product, tasks=len(base_tasks))
        return {
            "plan_id": plan_id,
            "product": product,
            "launch_type": launch_type,
            "launch_date": launch_date.isoformat(),
            "tasks": base_tasks,
            "task_count": len(base_tasks),
        }
