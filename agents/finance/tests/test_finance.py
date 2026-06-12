"""Behavioral tests for the finance agent."""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task(action: str, **payload):
    from shared.types import AgentCapability, Task
    return Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.FINANCE,
        payload={"action": action, **payload},
    )


def _agent(cfg_overrides: dict | None = None):
    from agents._base import AgentConfig
    from agents.finance.main import FinanceAgent

    raw = {
        "agent_name": "finance",
        "enabled": True,
        "poll_interval_seconds": 5.0,
        "max_retries": 3,
        "llm_system_prompt": "You are a finance agent.",
        "custom": {
            "mrr_drop_alert_threshold": 0.05,
            "charge_spike_multiplier": 3.0,
            "refund_spike_count": 5,
            "failed_payment_spike_count": 10,
            "products": {"default": ""},
            "vendors": [
                {"name": "contabo", "category": "infrastructure"},
                {"name": "anthropic", "category": "ai_api"},
                {"name": "vercel", "category": "hosting"},
            ],
        },
        **(cfg_overrides or {}),
    }
    config = AgentConfig(**raw)
    with (
        patch("agents.finance.main.FinanceDB"),
        patch("agents.finance.main.MRRTracker"),
        patch("agents.finance.main.CostTracker"),
        patch("agents.finance.main.Forecaster"),
        patch("agents.finance.main.AnomalyDetector"),
        patch("agents.finance.main.UnitEconomicsCalculator"),
        patch("agents.finance.main.BaseAgent.__init__", lambda *a, **kw: None),
    ):
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.agent_name = "finance"
        agent.config = config
        agent._db = MagicMock()
        agent._mrr = MagicMock()
        agent._cost = MagicMock()
        agent._forecast = MagicMock()
        agent._anomaly = MagicMock()
        agent._unit_econ = MagicMock()
        agent._dispatch = {
            "mrr_snapshot": agent._mrr_snapshot,
            "cost_tracking": agent._cost_tracking,
            "revenue_forecast": agent._revenue_forecast,
            "anomaly_detect": agent._anomaly_detect,
            "unit_economics": agent._unit_economics,
        }
        return agent


# ---------------------------------------------------------------------------
# FinanceAgent — routing
# ---------------------------------------------------------------------------

class TestFinanceAgentRouting:
    def test_unknown_action_returns_failure(self):
        agent = _agent()
        result = agent.handle(_task("nonexistent"))
        assert result.success is False
        assert "unknown action" in result.error

    def test_mrr_snapshot_routes_correctly(self):
        agent = _agent()
        agent._mrr.snapshot.return_value = {"date": "2026-06-12", "products": {}}
        result = agent.handle(_task("mrr_snapshot"))
        assert result.success is True
        agent._mrr.snapshot.assert_called_once()

    def test_cost_tracking_routes_correctly(self):
        agent = _agent()
        agent._cost.snapshot.return_value = {"total_cost_cents": 5000}
        agent._cost.gross_margin.return_value = {"gross_margin_pct": 80.0}
        agent._db.get_latest_mrr.return_value = {"mrr_cents": 100000}
        result = agent.handle(_task("cost_tracking"))
        assert result.success is True

    def test_revenue_forecast_routes_correctly(self):
        agent = _agent()
        agent._forecast.forecast.return_value = {"base": {"mrr_cents": 10000}}
        result = agent.handle(_task("revenue_forecast", product="default"))
        assert result.success is True
        agent._forecast.forecast.assert_called_once_with(product="default")

    def test_anomaly_detect_routes_correctly(self):
        agent = _agent()
        event = {"type": "charge.succeeded", "data": {"object": {}}}
        agent._anomaly.detect.return_value = {"anomalies": []}
        result = agent.handle(_task("anomaly_detect", event=event))
        assert result.success is True
        agent._anomaly.detect.assert_called_once_with(event)

    def test_unit_economics_routes_correctly(self):
        agent = _agent()
        agent._unit_econ.calculate.return_value = {"ltv_cac_ratio": 3.0}
        result = agent.handle(_task("unit_economics", sales_marketing_spend_cents=10000, new_customers=5))
        assert result.success is True
        agent._unit_econ.calculate.assert_called_once_with(
            sales_marketing_spend_cents=10000,
            new_customers=5,
        )

    def test_exception_in_handler_returns_failure(self):
        agent = _agent()
        agent._mrr.snapshot.side_effect = RuntimeError("stripe down")
        result = agent.handle(_task("mrr_snapshot"))
        assert result.success is False
        assert "stripe down" in result.error


# ---------------------------------------------------------------------------
# FinanceAgent — health_check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_check_true_when_db_ok(self):
        agent = _agent()
        agent._db.get_latest_mrr.return_value = {"mrr_cents": 5000}
        assert agent.health_check() is True

    def test_health_check_false_when_db_fails(self):
        agent = _agent()
        agent._db.get_latest_mrr.side_effect = Exception("db down")
        assert agent.health_check() is False


# ---------------------------------------------------------------------------
# MRRTracker
# ---------------------------------------------------------------------------

class TestMRRTracker:
    def _tracker(self, db=None):
        from agents.finance.mrr_tracker import MRRTracker
        cfg = {
            "mrr_drop_alert_threshold": 0.05,
            "products": {"default": ""},
        }
        return MRRTracker(cfg, db or MagicMock())

    def test_snapshot_stores_mrr_per_product(self):
        db = MagicMock()
        db.get_previous_mrr.return_value = None
        with patch("agents.finance.mrr_tracker.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 50000, "subscription_count": 10}
            tracker = self._tracker(db)
            result = tracker.snapshot()
        assert "products" in result
        assert "default" in result["products"]
        assert result["products"]["default"]["mrr_cents"] == 50000
        db.upsert_mrr_snapshot.assert_called_once()

    def test_snapshot_arr_is_mrr_times_12(self):
        db = MagicMock()
        db.get_previous_mrr.return_value = None
        with patch("agents.finance.mrr_tracker.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 10000, "subscription_count": 5}
            tracker = self._tracker(db)
            result = tracker.snapshot()
        assert result["products"]["default"]["arr_cents"] == 120000

    def test_no_alert_when_mrr_stable(self):
        db = MagicMock()
        db.get_previous_mrr.return_value = {"mrr_cents": 50000}
        with patch("agents.finance.mrr_tracker.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 49000, "subscription_count": 9}
            tracker = self._tracker(db)
            result = tracker.snapshot()
        assert result["alerts"] == []

    def test_alert_when_mrr_drops_more_than_threshold(self):
        db = MagicMock()
        db.get_previous_mrr.return_value = {"mrr_cents": 100000}
        with (
            patch("agents.finance.mrr_tracker.StripeConnector") as MockStripe,
            patch("agents.finance.mrr_tracker.TaskQueue"),
        ):
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 90000, "subscription_count": 18}
            tracker = self._tracker(db)
            result = tracker.snapshot()
        assert len(result["alerts"]) == 1
        assert result["alerts"][0]["drop_pct"] == 10.0

    def test_no_alert_when_no_previous_snapshot(self):
        db = MagicMock()
        db.get_previous_mrr.return_value = None
        with patch("agents.finance.mrr_tracker.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 50000, "subscription_count": 10}
            tracker = self._tracker(db)
            result = tracker.snapshot()
        assert result["alerts"] == []

    def test_alert_triggers_reporting_task(self):
        db = MagicMock()
        db.get_previous_mrr.return_value = {"mrr_cents": 100000}
        with (
            patch("agents.finance.mrr_tracker.StripeConnector") as MockStripe,
            patch("agents.finance.mrr_tracker.TaskQueue") as MockQueue,
        ):
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 90000, "subscription_count": 18}
            tracker = self._tracker(db)
            tracker.snapshot()
        MockQueue.return_value.push.assert_called_once()
        call_kwargs = MockQueue.return_value.push.call_args[1]
        assert call_kwargs["agent"] == "reporting"

    def test_product_specific_stripe_call_when_product_id_set(self):
        db = MagicMock()
        db.get_previous_mrr.return_value = None
        cfg = {
            "mrr_drop_alert_threshold": 0.05,
            "products": {"pro": "prod_abc123"},
        }
        from agents.finance.mrr_tracker import MRRTracker
        with patch("agents.finance.mrr_tracker.StripeConnector") as MockStripe:
            MockStripe.return_value.list_subscriptions.return_value = []
            tracker = MRRTracker(cfg, db)
            tracker.snapshot()
        MockStripe.return_value.list_subscriptions.assert_called_once_with(
            product="prod_abc123", status="active"
        )

    def test_snapshot_date_is_today(self):
        db = MagicMock()
        db.get_previous_mrr.return_value = None
        with patch("agents.finance.mrr_tracker.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 1000, "subscription_count": 1}
            tracker = self._tracker(db)
            result = tracker.snapshot()
        assert result["date"] == str(date.today())


# ---------------------------------------------------------------------------
# CostTracker
# ---------------------------------------------------------------------------

class TestCostTracker:
    def _tracker(self, db=None):
        from agents.finance.cost_tracker import CostTracker
        cfg = {
            "vendors": [
                {"name": "contabo", "category": "infrastructure"},
                {"name": "anthropic", "category": "ai_api"},
                {"name": "vercel", "category": "hosting"},
            ]
        }
        return CostTracker(cfg, db or MagicMock())

    def test_snapshot_upserts_per_vendor(self):
        db = MagicMock()
        with patch("agents.finance.cost_tracker.settings") as mock_settings:
            mock_settings.CONTABO_MONTHLY_COST_CENTS = "1500"
            mock_settings.ANTHROPIC_MONTHLY_COST_CENTS = "2000"
            mock_settings.VERCEL_MONTHLY_COST_CENTS = "500"
            tracker = self._tracker(db)
            result = tracker.snapshot()
        assert db.upsert_cost_snapshot.call_count == 3
        assert result["vendor_costs"]["contabo"] == 1500
        assert result["vendor_costs"]["anthropic"] == 2000
        assert result["vendor_costs"]["vercel"] == 500

    def test_total_cost_sums_all_vendors(self):
        db = MagicMock()
        with patch("agents.finance.cost_tracker.settings") as mock_settings:
            mock_settings.CONTABO_MONTHLY_COST_CENTS = "1000"
            mock_settings.ANTHROPIC_MONTHLY_COST_CENTS = "2000"
            mock_settings.VERCEL_MONTHLY_COST_CENTS = "500"
            tracker = self._tracker(db)
            result = tracker.snapshot()
        assert result["total_cost_cents"] == 3500
        assert result["total_cost_usd"] == 35.0

    def test_vendor_error_does_not_crash_snapshot(self):
        db = MagicMock()
        with patch("agents.finance.cost_tracker.settings") as mock_settings:
            del mock_settings.CONTABO_MONTHLY_COST_CENTS  # simulate missing
            mock_settings.ANTHROPIC_MONTHLY_COST_CENTS = "2000"
            mock_settings.VERCEL_MONTHLY_COST_CENTS = "500"
            tracker = self._tracker(db)
            result = tracker.snapshot()
        assert "total_cost_cents" in result  # still returns a result

    def test_gross_margin_calculated_correctly(self):
        db = MagicMock()
        db.get_total_cost_for_month.return_value = 20000  # $200
        tracker = self._tracker(db)
        result = tracker.gross_margin(mrr_cents=100000)
        assert result["gross_margin_pct"] == 80.0
        assert result["gross_profit_cents"] == 80000

    def test_gross_margin_zero_when_no_mrr(self):
        db = MagicMock()
        db.get_total_cost_for_month.return_value = 5000
        tracker = self._tracker(db)
        result = tracker.gross_margin(mrr_cents=0)
        assert result["gross_margin_pct"] == 0.0

    def test_period_month_is_first_of_month(self):
        db = MagicMock()
        with patch("agents.finance.cost_tracker.settings") as mock_settings:
            mock_settings.CONTABO_MONTHLY_COST_CENTS = "0"
            mock_settings.ANTHROPIC_MONTHLY_COST_CENTS = "0"
            mock_settings.VERCEL_MONTHLY_COST_CENTS = "0"
            tracker = self._tracker(db)
            result = tracker.snapshot()
        period = result["period_month"]
        assert period.endswith("-01")


# ---------------------------------------------------------------------------
# Forecaster
# ---------------------------------------------------------------------------

class TestForecaster:
    def _forecaster(self, db=None):
        from agents.finance.forecaster import Forecaster
        return Forecaster({}, db or MagicMock())

    def test_returns_empty_forecast_when_no_history(self):
        db = MagicMock()
        db.get_mrr_history.return_value = []
        forecaster = self._forecaster(db)
        result = forecaster.forecast()
        assert result["error"] == "no_data"
        assert result["base"]["mrr_cents"] == 0

    def test_llm_forecast_parsed_correctly(self):
        db = MagicMock()
        db.get_mrr_history.return_value = [
            {"snapshot_date": date(2026, 6, 1), "mrr_cents": 50000},
        ]
        llm_response = """{
            "low": {"mrr_cents": 45000, "arr_cents": 540000, "assumption": "churn increases"},
            "base": {"mrr_cents": 55000, "arr_cents": 660000, "assumption": "steady growth"},
            "high": {"mrr_cents": 70000, "arr_cents": 840000, "assumption": "viral growth"},
            "key_risks": ["churn", "competition"],
            "key_opportunities": ["new market"]
        }"""
        with patch("agents.finance.forecaster.llm") as mock_llm:
            mock_llm.complete.return_value = llm_response
            forecaster = self._forecaster(db)
            result = forecaster.forecast()
        assert result["base"]["mrr_cents"] == 55000
        assert result["high"]["mrr_cents"] == 70000
        assert "churn" in result["key_risks"]

    def test_parse_error_returns_empty_forecast(self):
        db = MagicMock()
        db.get_mrr_history.return_value = [{"snapshot_date": date.today(), "mrr_cents": 1000}]
        with patch("agents.finance.forecaster.llm") as mock_llm:
            mock_llm.complete.return_value = "not valid json at all"
            forecaster = self._forecaster(db)
            result = forecaster.forecast()
        assert result["error"] == "parse_error"

    def test_llm_exception_returns_empty_forecast(self):
        db = MagicMock()
        db.get_mrr_history.return_value = [{"snapshot_date": date.today(), "mrr_cents": 1000}]
        with patch("agents.finance.forecaster.llm") as mock_llm:
            mock_llm.complete.side_effect = Exception("timeout")
            forecaster = self._forecaster(db)
            result = forecaster.forecast()
        assert result["error"] == "llm_error"

    def test_forecast_includes_current_mrr(self):
        db = MagicMock()
        db.get_mrr_history.return_value = [{"snapshot_date": date.today(), "mrr_cents": 75000}]
        llm_response = '{"low": {"mrr_cents": 70000, "arr_cents": 840000, "assumption": ""}, "base": {"mrr_cents": 80000, "arr_cents": 960000, "assumption": ""}, "high": {"mrr_cents": 90000, "arr_cents": 1080000, "assumption": ""}, "key_risks": [], "key_opportunities": []}'
        with patch("agents.finance.forecaster.llm") as mock_llm:
            mock_llm.complete.return_value = llm_response
            forecaster = self._forecaster(db)
            result = forecaster.forecast()
        assert result["current_mrr_cents"] == 75000
        assert result["horizon_days"] == 90

    def test_forecast_product_passed_to_db(self):
        db = MagicMock()
        db.get_mrr_history.return_value = []
        forecaster = self._forecaster(db)
        forecaster.forecast(product="pro")
        db.get_mrr_history.assert_called_once_with(product="pro", days=90)


# ---------------------------------------------------------------------------
# AnomalyDetector
# ---------------------------------------------------------------------------

class TestAnomalyDetector:
    def _detector(self):
        from agents.finance.anomaly_detector import AnomalyDetector
        cfg = {
            "charge_spike_multiplier": 3.0,
            "refund_spike_count": 5,
            "failed_payment_spike_count": 10,
        }
        return AnomalyDetector(cfg)

    def test_charge_spike_detected(self):
        detector = self._detector()
        event = {
            "type": "charge.succeeded",
            "data": {"object": {"amount": 90000}},
        }
        with (
            patch("agents.finance.anomaly_detector.StripeConnector") as MockStripe,
            patch("agents.finance.anomaly_detector.TaskQueue"),
        ):
            MockStripe.return_value.get_revenue_report.return_value = {
                "net_cents": 30000,
                "transaction_count": 10,
            }
            detector._stripe = MockStripe.return_value
            result = detector.detect(event)
        assert len(result["anomalies"]) == 1
        assert result["anomalies"][0]["type"] == "charge_spike"

    def test_no_charge_spike_when_amount_is_normal(self):
        detector = self._detector()
        event = {
            "type": "charge.succeeded",
            "data": {"object": {"amount": 3500}},
        }
        with patch("agents.finance.anomaly_detector.StripeConnector") as MockStripe:
            MockStripe.return_value.get_revenue_report.return_value = {
                "net_cents": 30000,
                "transaction_count": 10,
            }
            detector._stripe = MockStripe.return_value
            result = detector.detect(event)
        assert result["anomalies"] == []

    def test_subscription_cancelled_always_logged(self):
        detector = self._detector()
        event = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_abc"}},
        }
        with patch("agents.finance.anomaly_detector.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 10000, "subscription_count": 9}
            detector._stripe = MockStripe.return_value
            result = detector.detect(event)
        assert len(result["anomalies"]) == 1
        assert result["anomalies"][0]["type"] == "subscription_cancelled"
        assert result["anomalies"][0]["cancelled_subscription_id"] == "sub_abc"

    def test_failed_payment_spike_detected(self):
        import time
        detector = self._detector()
        event = {
            "type": "invoice.payment_failed",
            "data": {"object": {"id": "inv_001"}},
        }
        # 12 recent failed invoices — above threshold of 10
        recent_invoices = [
            {"created": int(time.time()) - 3600, "attempt_count": 1}
            for _ in range(12)
        ]
        with (
            patch("agents.finance.anomaly_detector.StripeConnector") as MockStripe,
            patch("agents.finance.anomaly_detector.TaskQueue"),
        ):
            MockStripe.return_value.list_invoices.return_value = recent_invoices
            detector._stripe = MockStripe.return_value
            result = detector.detect(event)
        assert len(result["anomalies"]) == 1
        assert result["anomalies"][0]["type"] == "failed_payment_spike"

    def test_no_failed_payment_spike_below_threshold(self):
        import time
        detector = self._detector()
        event = {
            "type": "invoice.payment_failed",
            "data": {"object": {}},
        }
        recent_invoices = [
            {"created": int(time.time()) - 3600, "attempt_count": 1}
            for _ in range(3)
        ]
        with patch("agents.finance.anomaly_detector.StripeConnector") as MockStripe:
            MockStripe.return_value.list_invoices.return_value = recent_invoices
            detector._stripe = MockStripe.return_value
            result = detector.detect(event)
        assert result["anomalies"] == []

    def test_anomaly_notifies_reporting_and_sales(self):
        detector = self._detector()
        event = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_xyz"}},
        }
        with (
            patch("agents.finance.anomaly_detector.StripeConnector") as MockStripe,
            patch("agents.finance.anomaly_detector.TaskQueue") as MockQueue,
        ):
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 1000, "subscription_count": 1}
            detector._stripe = MockStripe.return_value
            detector.detect(event)
        assert MockQueue.return_value.push.call_count == 2
        agents_notified = {
            call[1]["agent"]
            for call in MockQueue.return_value.push.call_args_list
        }
        assert agents_notified == {"reporting", "sales"}

    def test_no_notification_when_no_anomalies(self):
        detector = self._detector()
        event = {"type": "payment_intent.created", "data": {"object": {}}}
        with (
            patch("agents.finance.anomaly_detector.StripeConnector"),
            patch("agents.finance.anomaly_detector.TaskQueue") as MockQueue,
        ):
            detector.detect(event)
        MockQueue.return_value.push.assert_not_called()

    def test_unknown_event_type_returns_no_anomalies(self):
        detector = self._detector()
        event = {"type": "payout.created", "data": {"object": {}}}
        with patch("agents.finance.anomaly_detector.StripeConnector"):
            result = detector.detect(event)
        assert result["anomalies"] == []


# ---------------------------------------------------------------------------
# UnitEconomicsCalculator
# ---------------------------------------------------------------------------

class TestUnitEconomicsCalculator:
    def _calc(self, db=None):
        from agents.finance.unit_economics import UnitEconomicsCalculator
        return UnitEconomicsCalculator({}, db or MagicMock())

    def test_cac_calculated_correctly(self):
        db = MagicMock()
        with patch("agents.finance.unit_economics.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 100000, "subscription_count": 100}
            MockStripe.return_value.list_subscriptions.return_value = []
            calc = self._calc(db)
            result = calc.calculate(sales_marketing_spend_cents=50000, new_customers=10)
        # CAC = 50000 / 10 = 5000 cents
        assert result["cac_cents"] == 5000
        assert result["cac_usd"] == 50.0

    def test_ltv_uses_arpu_divided_by_churn(self):
        db = MagicMock()
        with patch("agents.finance.unit_economics.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 100000, "subscription_count": 100}
            MockStripe.return_value.list_subscriptions.return_value = []
            calc = self._calc(db)
            result = calc.calculate(sales_marketing_spend_cents=10000, new_customers=5)
        # ARPU = 100000 / 100 = 1000 cents; no churn → 36 months
        assert result["ltv_cents"] == 36000
        assert result["ltv_usd"] == 360.0

    def test_ltv_cac_ratio_computed(self):
        db = MagicMock()
        with patch("agents.finance.unit_economics.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 100000, "subscription_count": 100}
            MockStripe.return_value.list_subscriptions.return_value = []
            calc = self._calc(db)
            result = calc.calculate(sales_marketing_spend_cents=12000, new_customers=4)
        # CAC = 3000; LTV = 36000; ratio = 12.0
        assert result["ltv_cac_ratio"] == 12.0

    def test_payback_months_computed(self):
        db = MagicMock()
        with patch("agents.finance.unit_economics.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 100000, "subscription_count": 100}
            MockStripe.return_value.list_subscriptions.return_value = []
            calc = self._calc(db)
            result = calc.calculate(sales_marketing_spend_cents=10000, new_customers=10)
        # ARPU=1000; CAC=1000; payback = 1000/1000 = 1 month
        assert result["payback_months"] == 1.0

    def test_zero_new_customers_gives_zero_cac(self):
        db = MagicMock()
        with patch("agents.finance.unit_economics.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 50000, "subscription_count": 50}
            MockStripe.return_value.list_subscriptions.return_value = []
            calc = self._calc(db)
            result = calc.calculate(sales_marketing_spend_cents=5000, new_customers=0)
        assert result["cac_cents"] == 0

    def test_result_stored_in_db(self):
        db = MagicMock()
        with patch("agents.finance.unit_economics.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 20000, "subscription_count": 20}
            MockStripe.return_value.list_subscriptions.return_value = []
            calc = self._calc(db)
            calc.calculate(sales_marketing_spend_cents=6000, new_customers=3)
        db.upsert_unit_economics.assert_called_once()

    def test_period_month_is_first_of_month(self):
        db = MagicMock()
        with patch("agents.finance.unit_economics.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 10000, "subscription_count": 10}
            MockStripe.return_value.list_subscriptions.return_value = []
            calc = self._calc(db)
            result = calc.calculate(sales_marketing_spend_cents=0, new_customers=0)
        assert result["period_month"].endswith("-01")

    def test_churned_subs_reduce_ltv(self):
        db = MagicMock()
        import time
        recent_cancel = {"canceled_at": int(time.time()) - 86400}
        with patch("agents.finance.unit_economics.StripeConnector") as MockStripe:
            MockStripe.return_value.get_mrr.return_value = {"mrr_cents": 100000, "subscription_count": 100}
            MockStripe.return_value.list_subscriptions.return_value = [recent_cancel] * 6
            calc = self._calc(db)
            result = calc.calculate(sales_marketing_spend_cents=10000, new_customers=5)
        # churn_rate = 6 / (100 * 3) = 0.02; ltv = 1000 / 0.02 = 50000
        assert result["ltv_cents"] == 50000


# ---------------------------------------------------------------------------
# FinanceDB (via mocked psycopg2)
# ---------------------------------------------------------------------------

class TestFinanceDB:
    def _db(self):
        from agents.finance.db import FinanceDB
        return FinanceDB()

    def test_upsert_mrr_snapshot_executes_sql(self):
        db = self._db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = (str(uuid.uuid4()),)
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        with patch("agents.finance.db.get_db", return_value=mock_conn):
            record_id = db.upsert_mrr_snapshot(
                snapshot_date=date(2026, 6, 1),
                product="default",
                mrr_cents=50000,
                arr_cents=600000,
                subscriber_count=10,
            )
        assert record_id is not None
        mock_cur.execute.assert_called_once()
        sql = mock_cur.execute.call_args[0][0]
        assert "ON CONFLICT" in sql

    def test_get_latest_mrr_returns_none_when_empty(self):
        db = self._db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = None
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        with patch("agents.finance.db.get_db", return_value=mock_conn):
            result = db.get_latest_mrr()
        assert result is None

    def test_upsert_cost_snapshot_executes_sql(self):
        db = self._db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = (str(uuid.uuid4()),)
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        with patch("agents.finance.db.get_db", return_value=mock_conn):
            record_id = db.upsert_cost_snapshot(
                period_month=date(2026, 6, 1),
                vendor="contabo",
                cost_cents=1500,
            )
        assert record_id is not None

    def test_upsert_unit_economics_executes_sql(self):
        db = self._db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = (str(uuid.uuid4()),)
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        with patch("agents.finance.db.get_db", return_value=mock_conn):
            record_id = db.upsert_unit_economics(
                period_month=date(2026, 6, 1),
                cac_cents=3000,
                ltv_cents=36000,
                ltv_cac_ratio=12.0,
                payback_months=3.0,
                new_customers=5,
                sales_marketing_spend_cents=15000,
            )
        assert record_id is not None
        sql = mock_cur.execute.call_args[0][0]
        assert "ON CONFLICT" in sql


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------

class TestCeleryTasks:
    """Tests for Celery task definitions and their behavior."""

    # Import task module functions directly (bypassing the Celery decorator
    # which wraps them in a MagicMock in test environments).
    def _task_fn(self, name: str):
        """Return the raw function from the tasks module by name."""
        import importlib
        import sys
        # Force fresh import to get module-level functions
        mod = sys.modules.get("agents.finance.tasks")
        if mod is None:
            import agents.finance.tasks as mod
        # Each task function body lives as a closure; access via __wrapped__
        # if decorated, otherwise directly from the module dict.
        fn = getattr(mod, name)
        # When Celery is mocked, @app.task() returns a MagicMock wrapping the fn.
        # The original function is stored as .__wrapped__ by functools or we
        # can replicate the task body from the tasks module directly.
        return fn

    def test_daily_mrr_snapshot_task_registered(self):
        import agents.finance.tasks as tasks_mod
        assert hasattr(tasks_mod, "daily_mrr_snapshot")

    def test_monthly_cost_tracking_task_registered(self):
        import agents.finance.tasks as tasks_mod
        assert hasattr(tasks_mod, "monthly_cost_tracking")

    def test_monthly_revenue_forecast_task_registered(self):
        import agents.finance.tasks as tasks_mod
        assert hasattr(tasks_mod, "monthly_revenue_forecast")

    def test_monthly_unit_economics_task_registered(self):
        import agents.finance.tasks as tasks_mod
        assert hasattr(tasks_mod, "monthly_unit_economics")

    def test_stripe_webhook_anomaly_task_registered(self):
        import agents.finance.tasks as tasks_mod
        assert hasattr(tasks_mod, "stripe_webhook_anomaly")

    def test_task_helper_builds_finance_task(self):
        """_task() produces a Task with AgentCapability.FINANCE."""
        import agents.finance.tasks as tasks_mod
        from shared.types import AgentCapability
        t = tasks_mod._task("mrr_snapshot")
        assert t.agent == AgentCapability.FINANCE
        assert t.payload["action"] == "mrr_snapshot"

    def test_task_helper_passes_extra_payload(self):
        import agents.finance.tasks as tasks_mod
        t = tasks_mod._task("anomaly_detect", event={"type": "charge.succeeded"})
        assert t.payload["event"]["type"] == "charge.succeeded"

    def test_agent_factory_loads_finance_agent(self):
        """_agent() returns a FinanceAgent instance."""
        import agents.finance.tasks as tasks_mod
        from agents.finance.main import FinanceAgent
        with (
            patch("agents._base.config.AgentConfig.load") as mock_load,
            patch("agents.finance.main.FinanceDB"),
            patch("agents.finance.main.MRRTracker"),
            patch("agents.finance.main.CostTracker"),
            patch("agents.finance.main.Forecaster"),
            patch("agents.finance.main.AnomalyDetector"),
            patch("agents.finance.main.UnitEconomicsCalculator"),
            patch("agents._base.agent.redis.Redis"),
        ):
            cfg = MagicMock()
            cfg.custom = {}
            mock_load.return_value = cfg
            agent = tasks_mod._agent()
        assert isinstance(agent, FinanceAgent)


# ---------------------------------------------------------------------------
# AgentCapability enum
# ---------------------------------------------------------------------------

class TestAgentCapabilityEnum:
    def test_finance_capability_exists(self):
        from shared.types import AgentCapability
        assert AgentCapability.FINANCE == "finance"

    def test_finance_used_in_task(self):
        from shared.types import AgentCapability, Task
        t = Task(
            id="test-id",
            agent=AgentCapability.FINANCE,
            payload={"action": "mrr_snapshot"},
        )
        assert t.agent == AgentCapability.FINANCE
