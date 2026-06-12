"""
Performance monitor — daily metrics pull, LLM analysis, auto-actions.

Rules:
  CPA > target * 1.5 for 3 consecutive days → pause campaign
  ROAS > target * 1.2                         → increase budget by 20%
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from agents.integrations.connectors.google_ads import GoogleAdsConnector
from agents.integrations.connectors.meta_ads import MetaAdsConnector
from agents.integrations.connectors.slack import SlackConnector
from shared.config.settings import settings
from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .campaign_manager import CampaignManager
from .db import AdsDB

logger = get_logger(__name__)

_ANALYSIS_SYSTEM = """You are a paid advertising performance analyst.
Given campaign metrics, provide a concise assessment (3-5 sentences):
1. Whether performance is above/below target and by how much
2. The single most important lever to pull (pause, scale budget, rotate creative, adjust audience)
3. Confidence level in the data (flag if too early / too few impressions)
No bullet points. Be specific and quantitative."""


class PerformanceMonitor:

    def __init__(self, db: AdsDB, mgr: CampaignManager, cfg: dict[str, Any]) -> None:
        self._db = db
        self._mgr = mgr
        self._cfg = cfg
        self._queue = TaskQueue()
        self._cpa_mult = float(cfg.get("cpa_pause_multiplier", 1.5))
        self._roas_mult = float(cfg.get("roas_scale_multiplier", 1.2))
        self._breach_days = int(cfg.get("consecutive_cpa_breach_days", 3))
        self._scale_pct = float(cfg.get("budget_scale_pct", 0.20))

    def run(self, campaign_id: str | None = None) -> dict[str, Any]:
        campaigns = (
            [self._db.get_campaign(campaign_id)]
            if campaign_id
            else self._db.get_active_campaigns()
        )
        campaigns = [c for c in campaigns if c]

        paused: list[str] = []
        scaled: list[str] = []
        reviewed: list[dict[str, Any]] = []

        for campaign in campaigns:
            try:
                result = self._process_campaign(campaign)
                reviewed.append(result)
                if result.get("action") == "paused":
                    paused.append(str(campaign["id"]))
                elif result.get("action") == "budget_scaled":
                    scaled.append(str(campaign["id"]))
            except Exception as exc:
                logger.error(
                    "perf_monitor_campaign_failed",
                    campaign_id=campaign["id"],
                    error=str(exc),
                )

        return {
            "campaigns_reviewed": len(reviewed),
            "paused": paused,
            "budget_scaled": scaled,
        }

    def _process_campaign(self, campaign: dict[str, Any]) -> dict[str, Any]:
        cid = str(campaign["id"])
        platform = campaign["platform"]

        # Pull yesterday's metrics from the platform
        metrics = self._pull_metrics(campaign)
        if not metrics:
            return {"campaign_id": cid, "action": "no_data"}

        # Upsert into ad_performance
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        self._db.log_performance(
            campaign_id=cid,
            perf_date=yesterday,
            **metrics,
        )

        target_cpa = float(campaign.get("target_cpa") or 0)
        target_roas = float(campaign.get("target_roas") or 0)

        # LLM analysis
        analysis = self._analyze(campaign, metrics, target_cpa, target_roas)
        logger.info("perf_analysis", campaign_id=cid, analysis_preview=analysis[:80])

        action = "none"

        # CPA breach: pause if exceeded for N consecutive days
        if target_cpa > 0:
            breaches = self._db.consecutive_cpa_breaches(cid, target_cpa, self._cpa_mult)
            if breaches >= self._breach_days:
                self._mgr.pause(campaign)
                action = "paused"
                self._notify_pause(campaign, metrics, target_cpa, breaches)
                self._queue.push(
                    agent="strategy",
                    payload={
                        "action": "campaign_paused_alert",
                        "campaign_id": cid,
                        "product": campaign["product"],
                        "reason": f"CPA {metrics.get('cpa'):.2f} > target {target_cpa:.2f} × {self._cpa_mult} for {breaches} days",
                        "analysis": analysis,
                    },
                )
                return {"campaign_id": cid, "action": action, "analysis": analysis}

        # ROAS win: scale budget
        if target_roas > 0 and metrics.get("roas") and action == "none":
            if float(metrics["roas"]) > target_roas * self._roas_mult:
                old_budget = float(campaign.get("budget_daily", 0))
                new_budget = old_budget * (1 + self._scale_pct)
                self._mgr.update_budget(campaign, new_budget)
                action = "budget_scaled"
                logger.info(
                    "budget_scaled_roas",
                    campaign_id=cid,
                    old=old_budget,
                    new=new_budget,
                    roas=metrics["roas"],
                )

        return {
            "campaign_id": cid,
            "action": action,
            "metrics": metrics,
            "analysis": analysis,
        }

    def _pull_metrics(self, campaign: dict[str, Any]) -> dict[str, Any] | None:
        platform = campaign["platform"]
        platform_id = campaign.get("platform_campaign_id", "")
        if not platform_id:
            return None

        try:
            if platform == "google":
                return self._pull_google(campaign)
            else:
                return self._pull_meta(campaign)
        except Exception as exc:
            logger.error(
                "pull_metrics_failed",
                campaign_id=campaign["id"],
                platform=platform,
                error=str(exc),
            )
            return None

    def _pull_google(self, campaign: dict[str, Any]) -> dict[str, Any] | None:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        ds = yesterday.isoformat()
        google = GoogleAdsConnector(called_by="ads", method_name="get_performance")
        rows = google.get_performance(
            campaign_ids=[campaign["platform_campaign_id"]],
            start_date=ds,
            end_date=ds,
        )
        if not rows:
            return None
        row = rows[0]
        metrics = row.get("metrics", {})
        cost = int(metrics.get("costMicros", 0)) / 1_000_000
        impressions = int(metrics.get("impressions", 0))
        clicks = int(metrics.get("clicks", 0))
        conversions = float(metrics.get("conversions", 0))
        ctr = clicks / impressions if impressions > 0 else 0.0
        cpa = cost / conversions if conversions > 0 else None
        return {
            "spend": cost,
            "impressions": impressions,
            "clicks": clicks,
            "conversions": conversions,
            "cpa": cpa,
            "roas": None,
            "ctr": ctr,
            "frequency": None,
        }

    def _pull_meta(self, campaign: dict[str, Any]) -> dict[str, Any] | None:
        meta = MetaAdsConnector(called_by="ads", method_name="get_insights")
        data = meta.get_campaign_insights(
            campaign_id=campaign["platform_campaign_id"],
            fields=["impressions", "clicks", "spend", "ctr", "conversions", "frequency"],
            date_preset="yesterday",
        )
        rows = data.get("data", [])
        if not rows:
            return None
        row = rows[0]
        spend = float(row.get("spend", 0))
        impressions = int(row.get("impressions", 0))
        clicks = int(row.get("clicks", 0))

        # Conversions is an array of action objects in Meta
        conv_raw = row.get("conversions", [])
        conversions = (
            sum(float(a.get("value", 0)) for a in conv_raw)
            if isinstance(conv_raw, list)
            else float(conv_raw or 0)
        )
        cpa = spend / conversions if conversions > 0 else None
        ctr = float(row.get("ctr", 0)) / 100  # Meta returns as percentage string
        frequency = float(row.get("frequency", 0)) if row.get("frequency") else None

        return {
            "spend": spend,
            "impressions": impressions,
            "clicks": clicks,
            "conversions": conversions,
            "cpa": cpa,
            "roas": None,
            "ctr": ctr,
            "frequency": frequency,
        }

    def _analyze(
        self,
        campaign: dict[str, Any],
        metrics: dict[str, Any],
        target_cpa: float,
        target_roas: float,
    ) -> str:
        prompt = (
            f"Campaign: {campaign['name']} ({campaign['platform']}, {campaign['product']})\n"
            f"Target CPA: ${target_cpa:.2f} | Target ROAS: {target_roas:.1f}x\n\n"
            f"Yesterday's metrics:\n"
            f"  Spend: ${metrics.get('spend', 0):.2f}\n"
            f"  Impressions: {metrics.get('impressions', 0):,}\n"
            f"  Clicks: {metrics.get('clicks', 0):,}\n"
            f"  CTR: {(metrics.get('ctr') or 0) * 100:.2f}%\n"
            f"  Conversions: {metrics.get('conversions', 0):.1f}\n"
            f"  CPA: ${metrics.get('cpa') or 0:.2f}\n"
            f"  ROAS: {metrics.get('roas') or 0:.1f}x\n"
            f"  Frequency: {metrics.get('frequency') or 'N/A'}\n"
        )
        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_ANALYSIS_SYSTEM,
            max_tokens=200,
            metadata={"caller": "ads.performance_monitor"},
        ).content[0].text.strip()

    def _notify_pause(
        self,
        campaign: dict[str, Any],
        metrics: dict[str, Any],
        target_cpa: float,
        breach_days: int,
    ) -> None:
        try:
            channel = self._cfg.get("alert_channel", "#ads")
            slack = SlackConnector(called_by="ads", method_name="notify_pause")
            slack.send_message(
                channel,
                f"*Campaign paused — {campaign['name']}*\n"
                f"CPA ${metrics.get('cpa') or 0:.2f} exceeded ${target_cpa:.2f} × {self._cpa_mult} "
                f"for {breach_days} consecutive days. Strategy review queued.",
            )
        except Exception as exc:
            logger.warning("pause_slack_failed", error=str(exc))
