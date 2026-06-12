"""Sales agent unit tests — no external services required."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from agents._base import AgentConfig
from agents.sales.db import SalesDB
from agents.sales.mailer import SalesMailer
from agents.sales.churn_recovery import ChurnRecovery
from agents.sales.pricing_intel import PricingIntel, _SIGNIFICANCE_MARKER
from agents.sales.referral import ReferralTrigger
from agents.sales.trial_nudge import TrialNudge
from agents.sales.upgrade_nudge import UpgradeNudge
from agents.sales.win_back import WinBack
from shared.types import Task, TaskResult
from shared.types import AgentCapability


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "email": "owner@example.com",
        "product": "starpio",
        "plan": "trial",
        "company": "Best Pizza",
        "stripe_sub_id": None,
        "stripe_customer_id": None,
        "nps_score": None,
        "engagement_score": 50,
    }
    if overrides:
        base.update(overrides)
    return base


def _cfg() -> dict:
    return {
        "trial_nudge_stall_days": 3,
        "trial_nudge_inactivity_hours": 48,
        "upgrade_nudge_cooldown_days": 7,
        "trial_extension_days": 30,
        "win_back_min_days": 30,
        "win_back_max_days": 90,
        "win_back_cooldown_days": 90,
        "referral_nps_threshold": 8,
        "referral_active_days": 30,
        "from_email": "dutch@test.com",
        "from_name": "Dutch",
        "from_password": "secret",
    }


@pytest.fixture
def mock_db():
    return MagicMock(spec=SalesDB)


@pytest.fixture
def mock_mailer():
    m = MagicMock(spec=SalesMailer)
    m.send.return_value = "<mid@test>"
    return m


@pytest.fixture
def cfg():
    return _cfg()


# ---------------------------------------------------------------------------
# TestTrialNudge
# ---------------------------------------------------------------------------

class TestTrialNudge:

    def test_no_stalled_users_returns_zero(self, mock_db, mock_mailer, cfg):
        mock_db.stalled_trials.return_value = []
        result = TrialNudge(mock_db, mock_mailer, cfg).run()
        assert result == {"sent": 0, "skipped": 0, "total_stalled": 0}
        mock_mailer.send.assert_not_called()

    def test_user_on_cooldown_is_skipped(self, mock_db, mock_mailer, cfg):
        mock_db.stalled_trials.return_value = [_user()]
        mock_db.days_since_last_action.return_value = 2.0  # < 7 day cooldown
        result = TrialNudge(mock_db, mock_mailer, cfg).run()
        assert result["skipped"] == 1
        assert result["sent"] == 0
        mock_mailer.send.assert_not_called()

    def test_unknown_product_is_skipped(self, mock_db, mock_mailer, cfg):
        mock_db.stalled_trials.return_value = [_user({"product": "unknown_product"})]
        mock_db.days_since_last_action.return_value = float("inf")
        result = TrialNudge(mock_db, mock_mailer, cfg).run()
        assert result["skipped"] == 1
        mock_mailer.send.assert_not_called()

    @patch("agents.sales.trial_nudge.llm")
    def test_eligible_user_gets_email_sent(self, mock_llm, mock_db, mock_mailer, cfg):
        user = _user({"product": "oneserv"})
        mock_db.stalled_trials.return_value = [user]
        mock_db.days_since_last_action.return_value = float("inf")

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Email body.")]
        mock_llm.complete.return_value = mock_resp

        result = TrialNudge(mock_db, mock_mailer, cfg).run()
        assert result["sent"] == 1
        mock_mailer.send.assert_called_once()
        mock_db.log_action.assert_called_once()

    @patch("agents.sales.trial_nudge.llm")
    def test_mailer_exception_does_not_crash_batch(self, mock_llm, mock_db, mock_mailer, cfg):
        users = [_user({"id": str(uuid.uuid4()), "product": "starpio"}) for _ in range(3)]
        mock_db.stalled_trials.return_value = users
        mock_db.days_since_last_action.return_value = float("inf")

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Body")]
        mock_llm.complete.return_value = mock_resp
        mock_mailer.send.side_effect = Exception("SMTP down")

        result = TrialNudge(mock_db, mock_mailer, cfg).run()
        assert result["sent"] == 0
        assert result["total_stalled"] == 3


# ---------------------------------------------------------------------------
# TestUpgradeNudge
# ---------------------------------------------------------------------------

class TestUpgradeNudge:

    def test_no_candidates_returns_zero(self, mock_db, mock_mailer, cfg):
        mock_db.upgrade_candidates.return_value = []
        result = UpgradeNudge(mock_db, mock_mailer, cfg).run()
        assert result == {"sent": 0, "skipped": 0, "total_candidates": 0}

    def test_user_on_cooldown_is_skipped(self, mock_db, mock_mailer, cfg):
        u = _user({"plan": "starter", "last_blocked_feature": "bulk_dispatch", "blocked_attempts": 3})
        mock_db.upgrade_candidates.return_value = [u]
        mock_db.days_since_last_action.return_value = 3.0  # < 7 day cooldown
        result = UpgradeNudge(mock_db, mock_mailer, cfg).run()
        assert result["skipped"] == 1
        mock_mailer.send.assert_not_called()

    @patch("agents.sales.upgrade_nudge.llm")
    def test_eligible_user_gets_upgrade_email(self, mock_llm, mock_db, mock_mailer, cfg):
        u = _user({"plan": "free", "last_blocked_feature": "auto_invoice", "blocked_attempts": 5})
        mock_db.upgrade_candidates.return_value = [u]
        mock_db.days_since_last_action.return_value = float("inf")

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Body text")]
        mock_llm.complete.return_value = mock_resp

        result = UpgradeNudge(mock_db, mock_mailer, cfg).run()
        assert result["sent"] == 1
        mock_mailer.send.assert_called_once()


# ---------------------------------------------------------------------------
# TestChurnRecovery
# ---------------------------------------------------------------------------

class TestChurnRecovery:

    def test_user_not_found_returns_error(self, mock_db, mock_mailer, cfg):
        mock_db.get_user.return_value = None
        result = ChurnRecovery(mock_db, mock_mailer, cfg).recover("missing-uid")
        assert result["error"] == "user_not_found"

    @patch("agents.sales.churn_recovery.llm")
    def test_no_stripe_sub_sends_email_without_extension(self, mock_llm, mock_db, mock_mailer, cfg):
        user = _user({"stripe_sub_id": None})
        mock_db.get_user.return_value = user
        mock_db.user_usage_summary.return_value = {"days_active": 10, "features_used": 2, "blocked_attempts": 0}
        mock_db.log_churn_recovery.return_value = str(uuid.uuid4())

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Email body")]
        mock_llm.complete.return_value = mock_resp

        result = ChurnRecovery(mock_db, mock_mailer, cfg).recover(user["id"])
        assert result["sent"] is True
        assert result["extension_applied"] is False
        mock_mailer.send.assert_called_once()

    @patch("agents.sales.churn_recovery.StripeConnector")
    @patch("agents.sales.churn_recovery.llm")
    def test_stripe_sub_applies_extension(self, mock_llm, mock_stripe_cls, mock_db, mock_mailer, cfg):
        user = _user({"stripe_sub_id": "sub_abc123"})
        mock_db.get_user.return_value = user
        mock_db.user_usage_summary.return_value = {"days_active": 15, "features_used": 3, "blocked_attempts": 2}
        mock_db.log_churn_recovery.return_value = str(uuid.uuid4())

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Email body")]
        mock_llm.complete.return_value = mock_resp

        mock_stripe_instance = MagicMock()
        mock_stripe_cls.return_value = mock_stripe_instance

        result = ChurnRecovery(mock_db, mock_mailer, cfg).recover(user["id"])
        assert result["sent"] is True
        assert result["extension_applied"] is True
        assert "trial_ext_30d" in result["stripe_coupon_id"]
        mock_stripe_instance.update_subscription.assert_called_once()

    @patch("agents.sales.churn_recovery.llm")
    def test_stripe_failure_still_sends_email(self, mock_llm, mock_db, mock_mailer, cfg):
        user = _user({"stripe_sub_id": "sub_fail"})
        mock_db.get_user.return_value = user
        mock_db.user_usage_summary.return_value = {}
        mock_db.log_churn_recovery.return_value = str(uuid.uuid4())

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Email body")]
        mock_llm.complete.return_value = mock_resp

        with patch("agents.sales.churn_recovery.StripeConnector") as mock_stripe_cls:
            mock_stripe_cls.return_value.update_subscription.side_effect = Exception("stripe error")
            result = ChurnRecovery(mock_db, mock_mailer, cfg).recover(user["id"])

        assert result["sent"] is True
        assert result["extension_applied"] is False


# ---------------------------------------------------------------------------
# TestWinBack
# ---------------------------------------------------------------------------

class TestWinBack:

    def test_no_churned_users(self, mock_db, mock_mailer, cfg):
        mock_db.churned_in_window.return_value = []
        result = WinBack(mock_db, mock_mailer, cfg).run()
        assert result == {"sent": 0, "skipped": 0, "total_churned": 0}

    def test_already_win_back_sent_is_skipped(self, mock_db, mock_mailer, cfg):
        mock_db.churned_in_window.return_value = [_user()]
        mock_db.win_back_sent_within.return_value = True
        result = WinBack(mock_db, mock_mailer, cfg).run()
        assert result["skipped"] == 1
        assert result["sent"] == 0

    @patch("agents.sales.win_back.llm")
    def test_step1_sent_and_step2_enqueued(self, mock_llm, mock_db, mock_mailer, cfg):
        user = _user()
        mock_db.churned_in_window.return_value = [user]
        mock_db.win_back_sent_within.return_value = False

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Step1 body")]
        mock_llm.complete.return_value = mock_resp

        with patch("agents.sales.win_back.TaskQueue") as mock_queue_cls:
            mock_queue = MagicMock()
            mock_queue_cls.return_value = mock_queue
            result = WinBack(mock_db, mock_mailer, cfg).run()

        assert result["sent"] == 1
        mock_mailer.send.assert_called_once()
        mock_queue.push.assert_called_once()
        call_kwargs = mock_queue.push.call_args
        assert call_kwargs[1]["agent"] == "sales" or call_kwargs[0][0] == "sales"

    @patch("agents.sales.win_back.llm")
    def test_send_step2_user_not_found(self, mock_llm, mock_db, mock_mailer, cfg):
        mock_db.get_user.return_value = None
        result = WinBack(mock_db, mock_mailer, cfg).send_step2("missing-uid")
        assert result["error"] == "user_not_found"

    @patch("agents.sales.win_back.llm")
    def test_send_step2_sends_email(self, mock_llm, mock_db, mock_mailer, cfg):
        user = _user()
        mock_db.get_user.return_value = user

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Step2 body")]
        mock_llm.complete.return_value = mock_resp

        result = WinBack(mock_db, mock_mailer, cfg).send_step2(user["id"])
        assert result["sent"] is True
        assert result["step"] == 2
        mock_mailer.send.assert_called_once()


# ---------------------------------------------------------------------------
# TestReferralTrigger
# ---------------------------------------------------------------------------

class TestReferralTrigger:

    def test_no_candidates_returns_zero(self, mock_db, mock_mailer, cfg):
        mock_db.referral_candidates.return_value = []
        result = ReferralTrigger(mock_db, mock_mailer, cfg).run()
        assert result == {"sent": 0, "total_candidates": 0}

    @patch("agents.sales.referral.llm")
    def test_sends_invite_to_happy_user(self, mock_llm, mock_db, mock_mailer, cfg):
        user = _user({"nps_score": 9, "product": "oneserv"})
        mock_db.referral_candidates.return_value = [user]

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Referral body")]
        mock_llm.complete.return_value = mock_resp

        result = ReferralTrigger(mock_db, mock_mailer, cfg).run()
        assert result["sent"] == 1
        mock_mailer.send.assert_called_once()
        mock_db.log_action.assert_called_once()

    @patch("agents.sales.referral.llm")
    def test_mailer_failure_continues(self, mock_llm, mock_db, mock_mailer, cfg):
        users = [_user({"nps_score": 9, "id": str(uuid.uuid4())}) for _ in range(2)]
        mock_db.referral_candidates.return_value = users

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Body")]
        mock_llm.complete.return_value = mock_resp
        mock_mailer.send.side_effect = Exception("SMTP")

        result = ReferralTrigger(mock_db, mock_mailer, cfg).run()
        assert result["sent"] == 0
        assert result["total_candidates"] == 2


# ---------------------------------------------------------------------------
# TestPricingIntel
# ---------------------------------------------------------------------------

class TestPricingIntel:

    def test_unknown_product_is_skipped(self, mock_db, cfg):
        result = PricingIntel(mock_db, cfg).run(products=["unknown_saas"])
        assert result["products_checked"] == 1
        assert result["alerts_sent"] == 0

    @patch("agents.sales.pricing_intel.web_search")
    @patch("agents.sales.pricing_intel.llm")
    def test_no_significant_change(self, mock_llm, mock_web_search, mock_db, cfg):
        mock_web_search.return_value = ["OpenTable costs $249/mo for basic plan."]
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Prices appear stable. Confidence: medium.")]
        mock_llm.complete.return_value = mock_resp

        with patch("agents.sales.pricing_intel.TaskQueue"):
            result = PricingIntel(mock_db, cfg).run(products=["starpio"])

        assert result["alerts_sent"] == 0
        assert result["results"]["starpio"]["significant"] is False

    @patch("agents.sales.pricing_intel.web_search")
    @patch("agents.sales.pricing_intel.llm")
    def test_significant_change_queues_strategy_alert(self, mock_llm, mock_web_search, mock_db, cfg):
        mock_web_search.return_value = ["OpenTable just dropped to $49/mo."]
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text=f"{_SIGNIFICANCE_MARKER} OpenTable dropped pricing significantly.")]
        mock_llm.complete.return_value = mock_resp

        with patch("agents.sales.pricing_intel.TaskQueue") as mock_queue_cls:
            mock_queue = MagicMock()
            mock_queue_cls.return_value = mock_queue
            result = PricingIntel(mock_db, cfg).run(products=["starpio"])

        assert result["alerts_sent"] == 1
        assert result["results"]["starpio"]["significant"] is True
        mock_queue.push.assert_called_once()
        push_kwargs = mock_queue.push.call_args[1]
        assert push_kwargs["agent"] == "strategy"
        assert push_kwargs["payload"]["product"] == "starpio"

    @patch("agents.sales.pricing_intel.web_search")
    @patch("agents.sales.pricing_intel.llm")
    def test_search_failure_returns_no_data(self, mock_llm, mock_web_search, mock_db, cfg):
        mock_web_search.side_effect = Exception("search down")
        result = PricingIntel(mock_db, cfg).run(products=["localoutrank"])
        assert result["results"]["localoutrank"]["analysis"] == "no_data"
        mock_llm.complete.assert_not_called()


# ---------------------------------------------------------------------------
# TestSalesAgentDispatch
# ---------------------------------------------------------------------------

class TestSalesAgentDispatch:

    def _make_agent(self):
        from agents.sales.main import SalesAgent

        config = AgentConfig(
            agent_name="sales",
            custom=_cfg(),
        )
        return SalesAgent("sales", config)

    def _task(self, payload: dict) -> Task:
        return Task(id=str(uuid.uuid4()), agent=AgentCapability.SALES, payload=payload)

    @patch("agents.sales.main.SalesDB")
    @patch("agents.sales.main.SalesMailer")
    def test_unknown_action_raises(self, _mock_mailer, _mock_db):
        agent = self._make_agent()
        with pytest.raises(ValueError, match="Unknown sales action"):
            agent.handle(self._task({"action": "totally_unknown"}))

    @patch("agents.sales.main.SalesDB")
    @patch("agents.sales.main.SalesMailer")
    def test_churn_recovery_missing_identifiers(self, _mock_mailer, _mock_db):
        agent = self._make_agent()
        result = agent.handle(self._task({"action": "churn_recovery"}))
        assert result.output["error"] == "user_id or stripe_customer_id required"

    @patch("agents.sales.main.SalesDB")
    @patch("agents.sales.main.SalesMailer")
    def test_churn_recovery_stripe_customer_not_found(self, _mock_mailer, mock_db_cls):
        agent = self._make_agent()
        agent._db.get_user_by_stripe_customer.return_value = None
        result = agent.handle(self._task({"action": "churn_recovery", "stripe_customer_id": "cus_missing"}))
        assert result.output["error"] == "user_not_found_for_stripe_customer"

    @patch("agents.sales.main.SalesDB")
    @patch("agents.sales.main.SalesMailer")
    def test_win_back_step2_requires_user_id(self, _mock_mailer, _mock_db):
        agent = self._make_agent()
        result = agent.handle(self._task({"action": "win_back", "sub_action": "step2"}))
        assert result.output["error"] == "user_id required for step2"

    @patch("agents.sales.main.SalesDB")
    @patch("agents.sales.main.SalesMailer")
    def test_successful_action_returns_task_result(self, _mock_mailer, _mock_db):
        agent = self._make_agent()
        agent._trial_nudge = MagicMock()
        agent._trial_nudge.run.return_value = {"sent": 0, "skipped": 0, "total_stalled": 0}
        result = agent.handle(self._task({"action": "trial_nudge"}))
        assert isinstance(result, TaskResult)
        assert result.success is True


# ---------------------------------------------------------------------------
# TestSalesDB (unit — no real DB required)
# ---------------------------------------------------------------------------

class TestSalesDB:

    def test_days_since_last_action_returns_inf_when_no_record(self):
        """Verify the query returns inf when no matching row exists (mocked cursor)."""
        db = SalesDB.__new__(SalesDB)
        with patch("agents.sales.db.get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = None
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = db.days_since_last_action("uid-123", "trial_nudge")
        assert result == float("inf")

    def test_win_back_sent_within_returns_false_when_no_record(self):
        db = SalesDB.__new__(SalesDB)
        with patch("agents.sales.db.get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = None
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = db.win_back_sent_within("uid-123", 90)
        assert result is False
