"""
Analytics Agent — revenue metrics, funnel analysis, and growth reporting.

Actions:
  revenue_snapshot    — Stripe MRR/ARR/churn + store time-series snapshot
  funnel_report       — PostHog step-by-step conversion funnel
  growth_dashboard    — Combined Stripe + GA4 + PostHog with LLM narrative
  cohort_analysis     — Monthly subscription cohorts from Stripe
  anomaly_alert       — Detect metric deviations and fire Slack alert
  product_usage_report — PostHog feature usage + LLM insights
"""
from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.db.client import get_db
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .alerter import AnalyticsAlerter
from .db import AnalyticsDB
from .metrics.ga4_metrics import GA4Metrics
from .metrics.posthog_metrics import PostHogMetrics
from .metrics.stripe_metrics import StripeMetrics
from .reporter import AnalyticsReporter

logger = get_logger(__name__)


class AnalyticsAgent(BaseAgent):
    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = AnalyticsDB()
        self._alerter = AnalyticsAlerter(self._db)
        self._reporter = AnalyticsReporter(self._db, self.ask_llm)
        self._report_ttl = int(cfg.get("report_cache_ttl_s", 3600))
        self._funnel_events: list[str] = cfg.get("funnel_events", [
            "signup",
            "trial_started",
            "payment_completed",
        ])

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "revenue_snapshot": lambda: self._revenue_snapshot(p, task.id),
            "funnel_report": lambda: self._funnel_report(p),
            "growth_dashboard": lambda: self._growth_dashboard(p, task.id),
            "cohort_analysis": lambda: self._cohort_analysis(p, task.id),
            "anomaly_alert": lambda: self._anomaly_alert(p),
            "product_usage_report": lambda: self._product_usage_report(p),
        }
        handler = dispatch.get(action)
        if not handler:
            raise ValueError(f"Unknown analytics action: {action!r}")

        logger.info("analytics_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM analytics_snapshots LIMIT 1")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Action: revenue_snapshot
    # ------------------------------------------------------------------

    def _revenue_snapshot(self, p: dict, task_id: str) -> dict[str, Any]:
        metrics = StripeMetrics(task_id=task_id).snapshot()

        snapshot_rows = [
            {"metric_type": k, "metric_value": v, "source": "stripe"}
            for k, v in metrics.items()
            if isinstance(v, (int, float))
        ]
        self._db.bulk_insert_snapshots(snapshot_rows)

        logger.info(
            "revenue_snapshot_stored",
            mrr=metrics.get("mrr"),
            arr=metrics.get("arr"),
            subs=metrics.get("subscription_count"),
        )
        return metrics

    # ------------------------------------------------------------------
    # Action: funnel_report
    # ------------------------------------------------------------------

    def _funnel_report(self, p: dict) -> dict[str, Any]:
        events = p.get("events", self._funnel_events)
        days = int(p.get("days", 30))
        ph = PostHogMetrics()
        funnel = ph.funnel(events, days=days)
        dau = ph.daily_active_users(days=7)
        new_users = ph.new_users(days=days)

        result: dict[str, Any] = {
            "funnel": funnel,
            "dau_7d": dau,
            "new_users": new_users,
            "days": days,
        }

        if funnel:
            self._db.insert_snapshot(
                metric_type="funnel_top_of_funnel",
                metric_value=funnel[0]["unique_users"],
                source="posthog",
            )
        return result

    # ------------------------------------------------------------------
    # Action: growth_dashboard
    # ------------------------------------------------------------------

    def _growth_dashboard(self, p: dict, task_id: str) -> dict[str, Any]:
        cached = self._db.get_cached_report("growth_dashboard")
        if cached and not p.get("force_refresh"):
            return {**cached, "cached": True}

        stripe = StripeMetrics(task_id=task_id).snapshot()
        ph = PostHogMetrics()
        posthog = {
            "dau_7d": ph.daily_active_users(7),
            "sessions_7d": ph.session_count(7),
            "new_users_30d": ph.new_users(30),
        }

        try:
            ga4 = GA4Metrics(task_id=task_id).web_overview(days=7)
        except Exception as exc:
            logger.warning("ga4_fetch_failed", error=str(exc))
            ga4 = {}

        return self._reporter.build_growth_dashboard(
            stripe_metrics=stripe,
            posthog_metrics=posthog,
            ga4_metrics=ga4,
            ttl_seconds=self._report_ttl,
        )

    # ------------------------------------------------------------------
    # Action: cohort_analysis
    # ------------------------------------------------------------------

    def _cohort_analysis(self, p: dict, task_id: str) -> dict[str, Any]:
        months = int(p.get("months", 6))
        cohorts = StripeMetrics(task_id=task_id).monthly_cohorts(months=months)

        for c in cohorts:
            self._db.insert_snapshot(
                metric_type="monthly_new_subscriptions",
                metric_value=c["new_subscriptions"],
                source="stripe",
                metadata={"month": c["month"]},
            )

        ph = PostHogMetrics()
        weekly_retention = ph.retention_by_week(weeks=8)

        return {
            "stripe_cohorts": cohorts,
            "posthog_weekly_retention": weekly_retention,
        }

    # ------------------------------------------------------------------
    # Action: anomaly_alert
    # ------------------------------------------------------------------

    def _anomaly_alert(self, p: dict) -> dict[str, Any]:
        metrics_to_check = p.get("metrics", ["mrr", "arr", "subscription_count"])
        current: dict[str, float] = {}
        for metric_type in metrics_to_check:
            latest = self._db.get_latest_snapshot(metric_type)
            if latest:
                current[metric_type] = float(latest["metric_value"])

        anomalies = self._alerter.check_and_alert(current)
        return {
            "anomalies_detected": len(anomalies),
            "anomalies": anomalies,
            "metrics_checked": list(current.keys()),
        }

    # ------------------------------------------------------------------
    # Action: product_usage_report
    # ------------------------------------------------------------------

    def _product_usage_report(self, p: dict) -> dict[str, Any]:
        days = int(p.get("days", 7))
        ph = PostHogMetrics()
        top_features = ph.top_features(days=days)
        funnel = ph.funnel(self._funnel_events, days=days)

        return self._reporter.build_product_usage_report(
            top_features=top_features,
            funnel=funnel,
            ttl_seconds=self._report_ttl,
        )


if __name__ == "__main__":
    config = AgentConfig.load("analytics")
    AnalyticsAgent("analytics", config).run()
