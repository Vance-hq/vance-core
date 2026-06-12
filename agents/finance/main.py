"""Finance agent — MRR snapshots, cost tracking, forecasting, anomaly detection, unit economics."""

from __future__ import annotations

from agents._base import BaseAgent, AgentConfig
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .anomaly_detector import AnomalyDetector
from .cost_tracker import CostTracker
from .db import FinanceDB
from .forecaster import Forecaster
from .mrr_tracker import MRRTracker
from .unit_economics import UnitEconomicsCalculator

logger = get_logger(__name__)


class FinanceAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom or {}

        self._db = FinanceDB()
        self._mrr = MRRTracker(cfg, self._db)
        self._cost = CostTracker(cfg, self._db)
        self._forecast = Forecaster(cfg, self._db)
        self._anomaly = AnomalyDetector(cfg)
        self._unit_econ = UnitEconomicsCalculator(cfg, self._db)

        self._dispatch = {
            "mrr_snapshot": self._mrr_snapshot,
            "cost_tracking": self._cost_tracking,
            "revenue_forecast": self._revenue_forecast,
            "anomaly_detect": self._anomaly_detect,
            "unit_economics": self._unit_economics,
        }

    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        logger.info("finance_task_received", action=action, task_id=task.id)

        handler = self._dispatch.get(action)
        if not handler:
            return TaskResult(task_id=task.id, success=False, error=f"unknown action: {action}")

        try:
            output = handler(task.payload)
            return TaskResult(task_id=task.id, success=True, output=output)
        except Exception as exc:
            logger.error("finance_task_failed", action=action, error=str(exc))
            return TaskResult(task_id=task.id, success=False, error=str(exc))

    def health_check(self) -> bool:
        try:
            self._db.get_latest_mrr()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _mrr_snapshot(self, payload: dict) -> dict:
        return self._mrr.snapshot()

    def _cost_tracking(self, payload: dict) -> dict:
        result = self._cost.snapshot()
        mrr_data = self._db.get_latest_mrr()
        mrr_cents = mrr_data["mrr_cents"] if mrr_data else 0
        margin = self._cost.gross_margin(mrr_cents)
        result["gross_margin"] = margin
        return result

    def _revenue_forecast(self, payload: dict) -> dict:
        product = payload.get("product", "default")
        return self._forecast.forecast(product=product)

    def _anomaly_detect(self, payload: dict) -> dict:
        event = payload.get("event", {})
        return self._anomaly.detect(event)

    def _unit_economics(self, payload: dict) -> dict:
        spend = int(payload.get("sales_marketing_spend_cents", 0))
        new_customers = int(payload.get("new_customers", 0))
        return self._unit_econ.calculate(
            sales_marketing_spend_cents=spend,
            new_customers=new_customers,
        )


if __name__ == "__main__":
    config = AgentConfig.load("finance")
    FinanceAgent("finance", config).run()
