"""Forge daily performance summary for inclusion in the daily brief."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from shared.logger import get_logger

if TYPE_CHECKING:
    from .db import ForgeDB

logger = get_logger(__name__)


class ForgeReporter:
    def __init__(self, db: "ForgeDB") -> None:
        self._db = db

    def daily_summary(self) -> dict[str, Any]:
        today = date.today().isoformat()
        metrics = self._db.get_daily_metrics(today)
        sequences = self._db.get_active_sequences()

        hot_count = self._db.count_leads_by_status("HOT")
        converted_count = self._db.count_leads_by_status("CONVERTED")

        open_rate = (
            round(metrics["opens"] / metrics["sends"], 3)
            if metrics["sends"] > 0 else 0.0
        )
        reply_rate = (
            round(metrics["replies"] / metrics["sends"], 3)
            if metrics["sends"] > 0 else 0.0
        )

        summary = {
            "date": today,
            "active_sequences": len(sequences),
            "sends_today": metrics["sends"],
            "opens_today": metrics["opens"],
            "replies_today": metrics["replies"],
            "bounces_today": metrics["bounces"],
            "open_rate": open_rate,
            "reply_rate": reply_rate,
            "hot_leads_total": hot_count,
            "converted_total": converted_count,
            "sequences": [
                {
                    "id": str(s["id"]),
                    "name": s["name"],
                    "product": s["product"],
                    "status": s["status"],
                }
                for s in sequences
            ],
        }
        logger.info("forge_daily_summary", date=today, sends=metrics["sends"], hot=hot_count)
        return summary
