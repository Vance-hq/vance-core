"""Ads agent unit tests — no external services required."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from agents._base import AgentConfig
from agents.ads.budget_reallocator import BudgetReallocator
from agents.ads.creative_gen import CreativeGenerator
from agents.ads.creative_rotator import CreativeRotator
from agents.ads.db import AdsDB
from shared.types import AgentCapability, Task, TaskResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _campaign(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "product": "starpio",
        "platform": "google",
        "name": "starpio — google — conversions — 1",
        "objective": "conversions",
        "status": "active",
        "budget_daily": 50.0,
        "platform_campaign_id": "customers/123/campaigns/456",
        "platform_ad_set_id": None,
        "platform_budget_resource": "customers/123/campaignBudgets/789",
        "target_cpa": 25.0,
        "target_roas": 3.0,
        "created_at": datetime.now(timezone.utc),
        "paused_at": None,
    }
    if overrides:
        base.update(overrides)
    return base


def _perf(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "campaign_id": str(uuid.uuid4()),
        "date": date.today(),
        "spend": 40.0,
        "impressions": 10000,
        "clicks": 250,
        "conversions": 5.0,
        "cpa": 8.0,
        "roas": 3.5,
        "ctr": 0.025,
        "frequency": None,
    }
    if overrides:
        base.update(overrides)
    return base


def _cfg() -> dict:
    return {
        "min_daily_budget": 5.0,
        "cpa_pause_multiplier": 1.5,
        "roas_scale_multiplier": 1.2,
        "consecutive_cpa_breach_days": 3,
        "budget_scale_pct": 0.20,
        "ctr_drop_threshold": 0.20,
        "frequency_threshold": 3.0,
        "ab_min_impressions": 500,
        "audience_expand_days": 28,
        "product_targets": {
            "starpio": {"target_cpa": 25.0, "target_roas": 3.0},
            "oneserv": {"target_cpa": 40.0, "target_roas": 2.5},
        },
        "alert_channel": "#ads",
        "google_conversion_action": "customers/123/conversionActions/456",
        "meta_pixel_id": "pixel_abc123",
    }


@pytest.fixture
def mock_db():
    return MagicMock(spec=AdsDB)


@pytest.fixture
def cfg():
    return _cfg()


# ---------------------------------------------------------------------------
# TestCreativeGenerator
# ---------------------------------------------------------------------------

class TestCreativeGenerator:

    @patch("agents.ads.creative_gen.llm")
    def test_google_returns_structured_creative(self, mock_llm):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text='{"headlines":["Fix Reviews Fast","Protect Your Rating","Reply in 60 Seconds","Manage All Reviews","Review Dashboard"],"descriptions":["Stop ignoring reviews. Respond in 60 seconds with Starpio. Free trial.","All your Google and Yelp reviews in one place. Reply, track, grow.","Starpio helps restaurant owners respond to reviews and win more guests.","See how your review score compares to nearby restaurants.","One dashboard for all your reviews. Start free, no card needed."],"ctas":["Start Free Trial","See Demo","Get Started"]}')]
        mock_llm.complete.return_value = mock_resp

        gen = CreativeGenerator()
        result = gen.generate(
            product="starpio",
            platform="google",
            objective="conversions",
            audience="restaurant owners",
            creative_brief="focus on protecting their reputation",
        )

        assert len(result["headlines"]) == 5
        assert len(result["descriptions"]) == 5
        assert len(result["ctas"]) == 3
        assert result["image_prompts"] == []

    @patch("agents.ads.creative_gen.llm")
    def test_meta_returns_image_prompts(self, mock_llm):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text='{"headlines":["Tired of Bad Reviews?","One Bad Review Can Cost You","Your Reviews, Under Control","What Are Guests Saying?","Review Blindspot?"],"descriptions":["Starpio helps restaurant owners respond to every review in 60 seconds. Free trial.","See and respond to all your Google and Yelp reviews from one place.","Most restaurants lose guests to unanswered reviews. See how many you\'re missing.","Track your review score and respond faster than your competition.","Starpio alerts you the moment a new review lands. Try it free today."],"ctas":["Try Free","See How It Works","Get My Score"],"image_prompts":["A restaurant owner reviewing feedback on a tablet at an empty dining table, morning light, professional photography","A close-up of a phone showing a 5-star Google review notification, warm cafe background, natural light","A chef in an apron responding to a customer review on a laptop in a kitchen prep area, realistic photography"]}')]
        mock_llm.complete.return_value = mock_resp

        gen = CreativeGenerator()
        result = gen.generate(
            product="starpio",
            platform="meta",
            objective="leads",
            audience="restaurant owners 35-55",
            creative_brief="show the pain of missed reviews",
        )

        assert len(result["image_prompts"]) == 3

    @patch("agents.ads.creative_gen.llm")
    def test_malformed_llm_response_returns_fallback(self, mock_llm):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Here are some headlines for you: blah blah blah")]
        mock_llm.complete.return_value = mock_resp

        gen = CreativeGenerator()
        result = gen.generate(
            product="oneserv",
            platform="google",
            objective="traffic",
            audience="contractors",
            creative_brief="dispatch jobs faster",
        )

        assert isinstance(result["headlines"], list)
        assert isinstance(result["ctas"], list)


# ---------------------------------------------------------------------------
# TestCreativeRotator
# ---------------------------------------------------------------------------

class TestCreativeRotator:

    def test_no_rotation_needed_when_ctr_stable(self, mock_db, cfg):
        cid = str(uuid.uuid4())
        campaign = _campaign({"id": cid})
        mock_db.get_active_campaigns.return_value = [campaign]
        mock_db.get_running_tests.return_value = []

        # Stable CTR: same both weeks
        perf_14 = [_perf({"ctr": 0.025, "frequency": None}) for _ in range(14)]
        mock_db.get_recent_performance.return_value = perf_14

        rotator = CreativeRotator(mock_db, MagicMock(), cfg)
        result = rotator.run()
        assert result["rotations"] == 0

    def test_rotation_triggered_by_ctr_drop(self, mock_db, cfg):
        cid = str(uuid.uuid4())
        campaign = _campaign({"id": cid})
        mock_db.get_active_campaigns.return_value = [campaign]
        mock_db.get_running_tests.return_value = []

        # This week CTR 0.010, last week 0.030 → 66% drop (> 20% threshold)
        this_week = [_perf({"ctr": 0.010}) for _ in range(7)]
        last_week = [_perf({"ctr": 0.030}) for _ in range(7)]
        mock_db.get_recent_performance.return_value = this_week + last_week

        mock_gen = MagicMock(spec=CreativeGenerator)
        mock_gen.generate_for_rotation.return_value = {
            "headlines": ["New Headline Test"],
            "descriptions": ["New Description Test"],
            "ctas": ["Try Now"],
            "image_prompts": [],
        }
        mock_db.create_creative_test.return_value = str(uuid.uuid4())

        rotator = CreativeRotator(mock_db, mock_gen, cfg)
        result = rotator.run()
        assert result["rotations"] == 1

    def test_rotation_triggered_by_meta_frequency(self, mock_db, cfg):
        cid = str(uuid.uuid4())
        campaign = _campaign({"id": cid, "platform": "meta"})
        mock_db.get_active_campaigns.return_value = [campaign]
        mock_db.get_running_tests.return_value = []

        # High frequency, stable CTR
        perf = [_perf({"ctr": 0.025, "frequency": 4.2}) for _ in range(14)]
        mock_db.get_recent_performance.return_value = perf

        mock_gen = MagicMock(spec=CreativeGenerator)
        mock_gen.generate_for_rotation.return_value = {
            "headlines": ["New Meta Headline"],
            "descriptions": ["New Meta Desc"],
            "ctas": ["Learn More"],
            "image_prompts": ["A plumber fixing pipes in a modern kitchen, professional photography"],
        }
        mock_db.create_creative_test.return_value = str(uuid.uuid4())

        with patch("agents.ads.creative_rotator.TaskQueue") as mock_q_cls:
            mock_q = MagicMock()
            mock_q_cls.return_value = mock_q
            rotator = CreativeRotator(mock_db, mock_gen, cfg)
            result = rotator.run()

        assert result["rotations"] == 1
        # Image prompt forwarded to content agent
        mock_q.push.assert_called()

    def test_ab_test_resolved_when_sufficient_impressions(self, mock_db, cfg):
        cid = str(uuid.uuid4())
        test_id = str(uuid.uuid4())
        campaign = _campaign({"id": cid})
        mock_db.get_active_campaigns.return_value = [campaign]

        # Test has enough impressions; A has better CTR
        mock_db.get_running_tests.return_value = [{
            "id": test_id,
            "campaign_id": cid,
            "impressions_a": 600,
            "impressions_b": 600,
            "clicks_a": 24,   # CTR 0.04
            "clicks_b": 12,   # CTR 0.02
        }]
        mock_db.get_recent_performance.return_value = [_perf() for _ in range(14)]

        rotator = CreativeRotator(mock_db, MagicMock(), cfg)
        result = rotator.run()

        assert result["tests_resolved"] == 1
        mock_db.resolve_test.assert_called_once_with(test_id, "a")

    def test_ab_test_not_resolved_below_min_impressions(self, mock_db, cfg):
        cid = str(uuid.uuid4())
        campaign = _campaign({"id": cid})
        mock_db.get_active_campaigns.return_value = [campaign]

        mock_db.get_running_tests.return_value = [{
            "id": str(uuid.uuid4()),
            "campaign_id": cid,
            "impressions_a": 200,  # < 500
            "impressions_b": 150,
            "clicks_a": 8,
            "clicks_b": 6,
        }]
        mock_db.get_recent_performance.return_value = [_perf() for _ in range(14)]

        rotator = CreativeRotator(mock_db, MagicMock(), cfg)
        result = rotator.run()

        assert result["tests_resolved"] == 0
        mock_db.resolve_test.assert_not_called()


# ---------------------------------------------------------------------------
# TestBudgetReallocator
# ---------------------------------------------------------------------------

class TestBudgetReallocator:

    def test_no_campaigns_returns_empty(self, mock_db, cfg):
        mock_db.all_campaigns_roas.return_value = []
        mock_mgr = MagicMock()
        result = BudgetReallocator(mock_db, mock_mgr, cfg).rebalance()
        assert result["campaigns"] == 0
        assert result["scaled_up"] == []

    def test_insufficient_roas_data_returns_unchanged(self, mock_db, cfg):
        mock_db.all_campaigns_roas.return_value = [
            {"id": str(uuid.uuid4()), "budget_daily": 50.0, "avg_roas": None, "platform": "google"},
        ]
        mock_mgr = MagicMock()
        result = BudgetReallocator(mock_db, mock_mgr, cfg).rebalance()
        assert result.get("note") == "insufficient_roas_data"

    def test_top_campaign_gets_budget_increase(self, mock_db, cfg):
        top_id = str(uuid.uuid4())
        bottom_id = str(uuid.uuid4())
        mock_db.all_campaigns_roas.return_value = [
            {"id": top_id,    "budget_daily": 100.0, "avg_roas": 5.0, "platform": "google", "platform_campaign_id": "c1", "platform_budget_resource": "b1", "product": "starpio"},
            {"id": bottom_id, "budget_daily": 100.0, "avg_roas": 1.2, "platform": "google", "platform_campaign_id": "c2", "platform_budget_resource": "b2", "product": "starpio"},
        ]
        top_campaign = _campaign({"id": top_id, "budget_daily": 100.0})
        bottom_campaign = _campaign({"id": bottom_id, "budget_daily": 100.0})
        mock_db.get_campaign.side_effect = lambda cid: top_campaign if cid == top_id else bottom_campaign

        mock_mgr = MagicMock()
        mock_mgr.update_budget.return_value = {"updated": True, "old_budget": 100.0, "new_budget": 120.0}

        result = BudgetReallocator(mock_db, mock_mgr, cfg).rebalance()
        assert len(result["scaled_up"]) == 1
        assert len(result["scaled_down"]) == 1

    def test_budget_floor_enforced(self, mock_db, cfg):
        bottom_id = str(uuid.uuid4())
        top_id = str(uuid.uuid4())
        mock_db.all_campaigns_roas.return_value = [
            {"id": top_id,    "budget_daily": 50.0, "avg_roas": 4.0, "platform": "google", "platform_campaign_id": "c1", "platform_budget_resource": "b1", "product": "starpio"},
            {"id": bottom_id, "budget_daily": 5.0,  "avg_roas": 0.5, "platform": "google", "platform_campaign_id": "c2", "platform_budget_resource": "b2", "product": "starpio"},
        ]
        top_campaign = _campaign({"id": top_id, "budget_daily": 50.0})
        # Bottom campaign already at floor ($5)
        bottom_campaign = _campaign({"id": bottom_id, "budget_daily": 5.0})
        mock_db.get_campaign.side_effect = lambda cid: top_campaign if cid == top_id else bottom_campaign

        mock_mgr = MagicMock()
        mock_mgr.update_budget.return_value = {"updated": True, "old_budget": 50.0, "new_budget": 60.0}

        result = BudgetReallocator(mock_db, mock_mgr, cfg).rebalance()
        # Bottom campaign already at floor — no scale down call for it
        scale_down_calls = [c for c in mock_mgr.update_budget.call_args_list
                            if c[0] and c[0][1] < 5.0]
        assert len(scale_down_calls) == 0


# ---------------------------------------------------------------------------
# TestAdsAgentDispatch
# ---------------------------------------------------------------------------

class TestAdsAgentDispatch:

    def _make_agent(self):
        from agents.ads.main import AdsAgent
        config = AgentConfig(agent_name="ads", custom=_cfg())
        return AdsAgent("ads", config)

    def _task(self, payload: dict) -> Task:
        return Task(id=str(uuid.uuid4()), agent=AgentCapability.ADS, payload=payload)

    @patch("agents.ads.main.AdsDB")
    @patch("agents.ads.main.CampaignManager")
    @patch("agents.ads.main.PerformanceMonitor")
    @patch("agents.ads.main.CreativeRotator")
    @patch("agents.ads.main.AudienceBuilder")
    @patch("agents.ads.main.BudgetReallocator")
    def test_unknown_action_raises(self, _br, _ab, _cr, _pm, _cm, _db):
        agent = self._make_agent()
        with pytest.raises(ValueError, match="Unknown ads action"):
            agent.handle(self._task({"action": "totally_unknown"}))

    @patch("agents.ads.main.AdsDB")
    @patch("agents.ads.main.CampaignManager")
    @patch("agents.ads.main.PerformanceMonitor")
    @patch("agents.ads.main.CreativeRotator")
    @patch("agents.ads.main.AudienceBuilder")
    @patch("agents.ads.main.BudgetReallocator")
    def test_create_campaign_missing_product_returns_error(self, _br, _ab, _cr, _pm, _cm, _db):
        agent = self._make_agent()
        result = agent.handle(self._task({"action": "create_campaign", "platform": "google"}))
        assert result.output["error"] == "product and platform required"

    @patch("agents.ads.main.AdsDB")
    @patch("agents.ads.main.CampaignManager")
    @patch("agents.ads.main.PerformanceMonitor")
    @patch("agents.ads.main.CreativeRotator")
    @patch("agents.ads.main.AudienceBuilder")
    @patch("agents.ads.main.BudgetReallocator")
    def test_create_campaign_invalid_platform_returns_error(self, _br, _ab, _cr, _pm, _cm, _db):
        agent = self._make_agent()
        result = agent.handle(self._task({
            "action": "create_campaign",
            "product": "starpio",
            "platform": "tiktok",
        }))
        assert "platform must be" in result.output["error"]

    @patch("agents.ads.main.AdsDB")
    @patch("agents.ads.main.CampaignManager")
    @patch("agents.ads.main.PerformanceMonitor")
    @patch("agents.ads.main.CreativeRotator")
    @patch("agents.ads.main.AudienceBuilder")
    @patch("agents.ads.main.BudgetReallocator")
    @patch("agents.ads.main.CreativeGenerator")
    def test_create_campaign_no_conversion_tracking_returns_error(
        self, mock_gen_cls, _br, _ab, _cr, mock_pm_cls, mock_cm_cls, mock_db_cls
    ):
        # Config without conversion tracking set
        cfg_no_tracking = {**_cfg(), "google_conversion_action": ""}
        from agents.ads.main import AdsAgent
        agent = AdsAgent("ads", AgentConfig(agent_name="ads", custom=cfg_no_tracking))

        mock_gen = MagicMock()
        mock_gen.generate.return_value = {
            "headlines": ["H1"], "descriptions": ["D1"], "ctas": ["CTA"], "image_prompts": []
        }
        mock_gen_cls.return_value = mock_gen
        agent._gen = mock_gen

        # CampaignManager.launch_google raises ValueError when no conversion action
        agent._mgr.launch_google.side_effect = ValueError("google_conversion_action not configured")
        agent._db.create_campaign.return_value = str(uuid.uuid4())
        agent._db.get_active_campaigns.return_value = []

        result = agent.handle(self._task({
            "action": "create_campaign",
            "product": "starpio",
            "platform": "google",
            "budget_daily": 20.0,
            "audience": "restaurant owners",
            "creative_brief": "reviews",
        }))
        assert "not_launched" in str(result.output)

    @patch("agents.ads.main.AdsDB")
    @patch("agents.ads.main.CampaignManager")
    @patch("agents.ads.main.PerformanceMonitor")
    @patch("agents.ads.main.CreativeRotator")
    @patch("agents.ads.main.AudienceBuilder")
    @patch("agents.ads.main.BudgetReallocator")
    def test_monitor_delegates_to_performance_monitor(self, _br, _ab, _cr, mock_pm_cls, _cm, _db):
        agent = self._make_agent()
        agent._monitor = MagicMock()
        agent._monitor.run.return_value = {"campaigns_reviewed": 3, "paused": [], "budget_scaled": []}
        result = agent.handle(self._task({"action": "monitor_performance"}))
        assert result.success is True
        agent._monitor.run.assert_called_once_with(campaign_id=None)

    @patch("agents.ads.main.AdsDB")
    @patch("agents.ads.main.CampaignManager")
    @patch("agents.ads.main.PerformanceMonitor")
    @patch("agents.ads.main.CreativeRotator")
    @patch("agents.ads.main.AudienceBuilder")
    @patch("agents.ads.main.BudgetReallocator")
    def test_budget_realloc_delegates_to_reallocator(self, mock_br_cls, _ab, _cr, _pm, _cm, _db):
        agent = self._make_agent()
        agent._reallocator = MagicMock()
        agent._reallocator.rebalance.return_value = {
            "campaigns": 5, "scaled_up": [], "scaled_down": [], "unchanged": []
        }
        result = agent.handle(self._task({"action": "budget_realloc"}))
        assert result.success is True
        agent._reallocator.rebalance.assert_called_once()


# ---------------------------------------------------------------------------
# TestAdsDB (unit — no real DB)
# ---------------------------------------------------------------------------

class TestAdsDB:

    def test_get_campaign_returns_none_when_missing(self):
        db = AdsDB.__new__(AdsDB)
        with patch("agents.ads.db.get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = None
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = db.get_campaign("nonexistent-id")
        assert result is None

    def test_consecutive_cpa_breaches_returns_zero_on_good_cpa(self):
        db = AdsDB.__new__(AdsDB)
        with patch("agents.ads.db.get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            # CPAs all below threshold
            mock_cur.fetchall.return_value = [(10.0,), (9.5,), (11.0,)]
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            # target_cpa=25, multiplier=1.5 → threshold=37.5, all below → 0 breaches
            result = db.consecutive_cpa_breaches("some-id", target_cpa=25.0, multiplier=1.5)
        assert result == 0

    def test_consecutive_cpa_breaches_counts_from_most_recent(self):
        db = AdsDB.__new__(AdsDB)
        with patch("agents.ads.db.get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            # Three consecutive breaches (50 > 37.5), then one good day
            mock_cur.fetchall.return_value = [(50.0,), (48.0,), (52.0,), (20.0,)]
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = db.consecutive_cpa_breaches("some-id", target_cpa=25.0, multiplier=1.5)
        assert result == 3
