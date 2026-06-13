"""CrossProductReporter — unified daily view across all products → reporting agent."""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import AnalyticsDB

logger = get_logger(__name__)

_SPIKE_THRESHOLD = 0.20


def _pct_change(current: float, prior: float) -> float | None:
    if prior == 0:
        return None
    return round((current - prior) / prior, 4)


class CrossProductReporter:

    def __init__(self, db: AnalyticsDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self) -> dict[str, Any]:
        products = list(self._cfg.get("products", {}).keys())
        today_rows = self._db.get_all_products_today()
        today_by_product = {r["product"]: r["metrics"] for r in today_rows}

        summaries = []
        anomalies = []
        total_active = 0

        for product in products:
            today_metrics = today_by_product.get(product, {})
            prior_rows = self._db.get_recent_usage(product=product, days=2)
            prior_metrics = prior_rows[1]["metrics"] if len(prior_rows) > 1 else {}

            active = int(today_metrics.get("active_users", today_metrics.get("unique_visitors", 0)))
            total_active += active

            changes = {}
            for key, val in today_metrics.items():
                if isinstance(val, (int, float)):
                    prior_val = float(prior_metrics.get(key, 0))
                    chg = _pct_change(float(val), prior_val)
                    changes[key] = {"value": val, "change_pct": chg}
                    if chg is not None and abs(chg) >= _SPIKE_THRESHOLD:
                        anomalies.append({
                            "product": product,
                            "metric": key,
                            "value": val,
                            "change_pct": chg,
                        })

            summaries.append({
                "product": product,
                "active_users": active,
                "metrics": today_metrics,
                "changes": changes,
            })

        report = {
            "total_active_users": total_active,
            "products": summaries,
            "anomalies": anomalies,
        }

        self._enqueue_reporting(report)
        logger.info("cross_product_report_sent", products=len(products), anomalies=len(anomalies))
        return report

    def _enqueue_reporting(self, report: dict[str, Any]) -> None:
        try:
            TaskQueue().push(
                agent="reporting",
                payload={"action": "add_to_brief", "section": "analytics", "data": report, "source": "analytics"},
            )
        except Exception as exc:
            logger.warning("enqueue_reporting_failed", error=str(exc))
