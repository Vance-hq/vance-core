"""
Budget reallocator — weekly ROAS-based budget rebalancing across campaigns.

Rules:
  - Sort active campaigns by 7-day average ROAS
  - Bottom 20%: reduce budget by 20% (floor: $5/day)
  - Top 20%: increase budget by 20%
  - Campaigns with no ROAS data are left unchanged
  - All changes logged to ad_budget_log
"""

from __future__ import annotations

import math
from typing import Any

from shared.logger import get_logger

from .campaign_manager import CampaignManager
from .db import AdsDB

logger = get_logger(__name__)

_SCALE_PCT = 0.20


class BudgetReallocator:

    def __init__(self, db: AdsDB, mgr: CampaignManager, cfg: dict[str, Any]) -> None:
        self._db = db
        self._mgr = mgr
        self._min_budget = float(cfg.get("min_daily_budget", 5.0))

    def rebalance(self) -> dict[str, Any]:
        rows = self._db.all_campaigns_roas(days=7)
        if not rows:
            return {"campaigns": 0, "scaled_up": [], "scaled_down": [], "unchanged": []}

        # Only rebalance campaigns that have ROAS data
        with_roas = [r for r in rows if r.get("avg_roas") is not None]
        without_roas = [r for r in rows if r.get("avg_roas") is None]

        if len(with_roas) < 2:
            return {
                "campaigns": len(rows),
                "scaled_up": [],
                "scaled_down": [],
                "unchanged": [str(r["id"]) for r in rows],
                "note": "insufficient_roas_data",
            }

        # Sort by avg ROAS descending
        with_roas.sort(key=lambda r: float(r["avg_roas"]), reverse=True)
        n = len(with_roas)
        top_n = max(1, math.ceil(n * 0.20))
        bottom_n = max(1, math.ceil(n * 0.20))

        top_tier = with_roas[:top_n]
        bottom_tier = with_roas[n - bottom_n:]
        unchanged = with_roas[top_n: n - bottom_n]

        scaled_up: list[dict[str, Any]] = []
        scaled_down: list[dict[str, Any]] = []

        for row in top_tier:
            campaign = self._db.get_campaign(str(row["id"]))
            if not campaign:
                continue
            old_budget = float(campaign.get("budget_daily", 0))
            new_budget = old_budget * (1 + _SCALE_PCT)
            result = self._mgr.update_budget(campaign, new_budget)
            if result.get("updated"):
                self._db.log_budget_change(
                    campaign_id=str(row["id"]),
                    old_budget=old_budget,
                    new_budget=result["new_budget"],
                    reason=f"weekly_realloc_scale_up roas={float(row['avg_roas']):.2f}",
                )
                scaled_up.append({
                    "campaign_id": str(row["id"]),
                    "old_budget": old_budget,
                    "new_budget": result["new_budget"],
                    "avg_roas": float(row["avg_roas"]),
                })

        for row in bottom_tier:
            campaign = self._db.get_campaign(str(row["id"]))
            if not campaign:
                continue
            old_budget = float(campaign.get("budget_daily", 0))
            new_budget = max(self._min_budget, old_budget * (1 - _SCALE_PCT))
            if new_budget >= old_budget:
                continue  # Already at floor
            result = self._mgr.update_budget(campaign, new_budget)
            if result.get("updated"):
                self._db.log_budget_change(
                    campaign_id=str(row["id"]),
                    old_budget=old_budget,
                    new_budget=result["new_budget"],
                    reason=f"weekly_realloc_scale_down roas={float(row['avg_roas']):.2f}",
                )
                scaled_down.append({
                    "campaign_id": str(row["id"]),
                    "old_budget": old_budget,
                    "new_budget": result["new_budget"],
                    "avg_roas": float(row["avg_roas"]),
                })

        unchanged_ids = [str(r["id"]) for r in unchanged + without_roas]

        logger.info(
            "budget_realloc_complete",
            scaled_up=len(scaled_up),
            scaled_down=len(scaled_down),
            unchanged=len(unchanged_ids),
        )
        return {
            "campaigns": len(rows),
            "scaled_up": scaled_up,
            "scaled_down": scaled_down,
            "unchanged": unchanged_ids,
        }
