"""Launch agent unit tests — no external services required."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from agents._base import AgentConfig
from agents.launch.db import LaunchDB
from agents.launch.planner import LaunchPlanner
from agents.launch.executor import LaunchExecutor
from agents.launch.product_hunt import ProductHuntLaunch
from agents.launch.debrief import LaunchDebrief
from shared.types import AgentCapability, Task, TaskResult


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_LAUNCH_DATE = date(2026, 7, 1)


def _plan(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "product": "starpio",
        "launch_type": "major_feature",
        "launch_date": _LAUNCH_DATE.isoformat(),
        "status": "planned",
        "tasks": json.dumps([
            {"offset_days": -14, "agent": "content",   "action": "write_blog",        "status": "pending", "critical": False},
            {"offset_days": -7,  "agent": "outreach",  "action": "early_access_email","status": "pending", "critical": True},
            {"offset_days": -3,  "agent": "video",     "action": "launch_video",      "status": "pending", "critical": False},
            {"offset_days": -1,  "agent": "content",   "action": "queue_social",      "status": "pending", "critical": False},
            {"offset_days":  0,  "agent": "content",   "action": "publish_all",       "status": "pending", "critical": True},
            {"offset_days":  0,  "agent": "marketing", "action": "launch_email",      "status": "pending", "critical": True},
            {"offset_days":  0,  "agent": "dev",       "action": "flip_feature_flag", "status": "pending", "critical": True},
            {"offset_days":  1,  "agent": "support",   "action": "proactive_faq",     "status": "pending", "critical": False},
            {"offset_days":  7,  "agent": "analytics", "action": "launch_report",     "status": "pending", "critical": False},
        ]),
    }
    if overrides:
        base.update(overrides)
    return base


def _result(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "launch_id": str(uuid.uuid4()),
        "metric": "signups",
        "value": "142",
        "recorded_at": datetime.now(timezone.utc),
    }
    if overrides:
        base.update(overrides)
    return base


@pytest.fixture
def mock_db():
    db = MagicMock(spec=LaunchDB)
    db.save_plan.return_value = str(uuid.uuid4())
    db.get_plan.return_value = _plan()
    db.list_pending_tasks.return_value = []
    db.update_task_status.return_value = None
    db.save_result.return_value = str(uuid.uuid4())
    db.get_results.return_value = [_result()]
    db.update_plan_status.return_value = None
    return db


@pytest.fixture
def cfg() -> dict:
    return {
        "products": {
            "starpio": {"name": "Starpio", "url": "https://starpio.com"},
            "oneserv": {"name": "Oneserv", "url": "https://oneserv.com"},
            "localoutrank": {"name": "LocalOutRank", "url": "https://localoutrank.com"},
        },
        "dutch_email": "dutch@vance.com",
        "resend_api_key": "re_test",
        "ph_notify_email": "dutch@vance.com",
    }


# ---------------------------------------------------------------------------
# LaunchDB
# ---------------------------------------------------------------------------

class TestLaunchDB:

    def _make_db(self):
        db = LaunchDB.__new__(LaunchDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        return db, mock_conn, mock_cur

    def test_save_plan_returns_id(self):
        db, mock_conn, mock_cur = self._make_db()
        expected_id = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected_id}
        with patch("agents.launch.db.get_db", return_value=mock_conn):
            result = db.save_plan(
                product="starpio",
                launch_type="major_feature",
                launch_date=_LAUNCH_DATE,
                tasks=[],
            )
        assert result == expected_id

    def test_get_plan_returns_dict(self):
        db, mock_conn, mock_cur = self._make_db()
        mock_cur.fetchone.return_value = _plan()
        with patch("agents.launch.db.get_db", return_value=mock_conn):
            result = db.get_plan(plan_id=str(uuid.uuid4()))
        assert result is not None
        assert result["product"] == "starpio"

    def test_get_plan_returns_none_when_missing(self):
        db, mock_conn, mock_cur = self._make_db()
        mock_cur.fetchone.return_value = None
        with patch("agents.launch.db.get_db", return_value=mock_conn):
            result = db.get_plan(plan_id="ghost-id")
        assert result is None

    def test_list_pending_tasks_returns_due_tasks(self):
        db, mock_conn, mock_cur = self._make_db()
        mock_cur.fetchall.return_value = [_plan()]
        with patch("agents.launch.db.get_db", return_value=mock_conn):
            results = db.list_pending_tasks(as_of=datetime.now(timezone.utc))
        assert isinstance(results, list)

    def test_save_result_returns_id(self):
        db, mock_conn, mock_cur = self._make_db()
        expected_id = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected_id}
        with patch("agents.launch.db.get_db", return_value=mock_conn):
            result = db.save_result(
                launch_id=str(uuid.uuid4()),
                metric="signups",
                value="142",
            )
        assert result == expected_id

    def test_update_plan_status(self):
        db, mock_conn, mock_cur = self._make_db()
        with patch("agents.launch.db.get_db", return_value=mock_conn):
            db.update_plan_status(plan_id=str(uuid.uuid4()), status="in_progress")
        mock_cur.execute.assert_called_once()


# ---------------------------------------------------------------------------
# LaunchPlanner
# ---------------------------------------------------------------------------

class TestLaunchPlanner:

    def test_plan_major_feature_creates_9_tasks(self, mock_db, cfg):
        planner = LaunchPlanner(mock_db, cfg)
        with patch("agents.launch.planner.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text="[]")]
            result = planner.plan(
                product="starpio",
                launch_type="major_feature",
                launch_date=_LAUNCH_DATE,
            )
        tasks = result["tasks"]
        assert len(tasks) >= 9

    def test_plan_includes_t0_tasks(self, mock_db, cfg):
        planner = LaunchPlanner(mock_db, cfg)
        with patch("agents.launch.planner.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text="[]")]
            result = planner.plan(
                product="starpio",
                launch_type="major_feature",
                launch_date=_LAUNCH_DATE,
            )
        t0_tasks = [t for t in result["tasks"] if t["offset_days"] == 0]
        assert len(t0_tasks) >= 3

    def test_plan_t0_includes_feature_flag_flip(self, mock_db, cfg):
        planner = LaunchPlanner(mock_db, cfg)
        with patch("agents.launch.planner.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text="[]")]
            result = planner.plan(
                product="starpio",
                launch_type="major_feature",
                launch_date=_LAUNCH_DATE,
            )
        agents_in_plan = [t["agent"] for t in result["tasks"]]
        assert "dev" in agents_in_plan

    def test_plan_new_product_includes_outreach(self, mock_db, cfg):
        planner = LaunchPlanner(mock_db, cfg)
        with patch("agents.launch.planner.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text="[]")]
            result = planner.plan(
                product="starpio",
                launch_type="new_product",
                launch_date=_LAUNCH_DATE,
            )
        agents_in_plan = [t["agent"] for t in result["tasks"]]
        assert "outreach" in agents_in_plan

    def test_plan_stores_to_db(self, mock_db, cfg):
        planner = LaunchPlanner(mock_db, cfg)
        with patch("agents.launch.planner.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text="[]")]
            planner.plan(
                product="starpio",
                launch_type="major_feature",
                launch_date=_LAUNCH_DATE,
            )
        mock_db.save_plan.assert_called_once()

    def test_plan_result_has_required_keys(self, mock_db, cfg):
        planner = LaunchPlanner(mock_db, cfg)
        with patch("agents.launch.planner.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text="[]")]
            result = planner.plan(
                product="starpio",
                launch_type="major_feature",
                launch_date=_LAUNCH_DATE,
            )
        for key in ("plan_id", "product", "launch_type", "launch_date", "tasks", "task_count"):
            assert key in result

    def test_plan_all_tasks_have_required_fields(self, mock_db, cfg):
        planner = LaunchPlanner(mock_db, cfg)
        with patch("agents.launch.planner.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text="[]")]
            result = planner.plan(
                product="starpio",
                launch_type="major_feature",
                launch_date=_LAUNCH_DATE,
            )
        for task in result["tasks"]:
            for field in ("offset_days", "agent", "action", "status", "critical"):
                assert field in task, f"task missing field: {field}"

    def test_plan_price_change_includes_marketing(self, mock_db, cfg):
        planner = LaunchPlanner(mock_db, cfg)
        with patch("agents.launch.planner.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text="[]")]
            result = planner.plan(
                product="localoutrank",
                launch_type="price_change",
                launch_date=_LAUNCH_DATE,
            )
        agents_in_plan = [t["agent"] for t in result["tasks"]]
        assert "marketing" in agents_in_plan

    def test_plan_post_launch_analytics_task(self, mock_db, cfg):
        planner = LaunchPlanner(mock_db, cfg)
        with patch("agents.launch.planner.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text="[]")]
            result = planner.plan(
                product="starpio",
                launch_type="major_feature",
                launch_date=_LAUNCH_DATE,
            )
        post_tasks = [t for t in result["tasks"] if t["offset_days"] > 0]
        post_agents = [t["agent"] for t in post_tasks]
        assert "analytics" in post_agents or "support" in post_agents


# ---------------------------------------------------------------------------
# LaunchExecutor
# ---------------------------------------------------------------------------

class TestLaunchExecutor:

    def test_execute_dispatches_due_tasks(self, mock_db, cfg):
        executor = LaunchExecutor(mock_db, cfg)
        due_task = {
            "plan_id": str(uuid.uuid4()),
            "task_idx": 0,
            "product": "starpio",
            "agent": "content",
            "action": "publish_all",
            "payload": {},
            "critical": True,
        }
        mock_db.list_pending_tasks.return_value = [due_task]
        with patch("agents.launch.executor.dispatch_to_agent") as mock_dispatch:
            mock_dispatch.return_value = {"success": True}
            result = executor.run()
        mock_dispatch.assert_called_once()
        assert result["tasks_dispatched"] == 1

    def test_execute_marks_task_completed_on_success(self, mock_db, cfg):
        executor = LaunchExecutor(mock_db, cfg)
        plan_id = str(uuid.uuid4())
        due_task = {
            "plan_id": plan_id,
            "task_idx": 2,
            "product": "starpio",
            "agent": "dev",
            "action": "flip_feature_flag",
            "payload": {},
            "critical": True,
        }
        mock_db.list_pending_tasks.return_value = [due_task]
        with patch("agents.launch.executor.dispatch_to_agent") as mock_dispatch:
            mock_dispatch.return_value = {"success": True}
            executor.run()
        mock_db.update_task_status.assert_called_once_with(
            plan_id=plan_id, task_idx=2, status="completed"
        )

    def test_execute_marks_task_failed_on_error(self, mock_db, cfg):
        executor = LaunchExecutor(mock_db, cfg)
        plan_id = str(uuid.uuid4())
        due_task = {
            "plan_id": plan_id,
            "task_idx": 1,
            "product": "starpio",
            "agent": "marketing",
            "action": "launch_email",
            "payload": {},
            "critical": False,
        }
        mock_db.list_pending_tasks.return_value = [due_task]
        with patch("agents.launch.executor.dispatch_to_agent") as mock_dispatch:
            mock_dispatch.side_effect = Exception("agent unreachable")
            result = executor.run()
        mock_db.update_task_status.assert_called_once_with(
            plan_id=plan_id, task_idx=1, status="failed"
        )
        assert result["tasks_failed"] == 1

    def test_execute_alerts_on_critical_failure(self, mock_db, cfg):
        executor = LaunchExecutor(mock_db, cfg)
        due_task = {
            "plan_id": str(uuid.uuid4()),
            "task_idx": 0,
            "product": "starpio",
            "agent": "dev",
            "action": "flip_feature_flag",
            "payload": {},
            "critical": True,
        }
        mock_db.list_pending_tasks.return_value = [due_task]
        with patch("agents.launch.executor.dispatch_to_agent") as mock_dispatch, \
             patch("agents.launch.executor.send_alert") as mock_alert:
            mock_dispatch.side_effect = Exception("deployment failed")
            executor.run()
        mock_alert.assert_called_once()

    def test_execute_no_alert_on_non_critical_failure(self, mock_db, cfg):
        executor = LaunchExecutor(mock_db, cfg)
        due_task = {
            "plan_id": str(uuid.uuid4()),
            "task_idx": 0,
            "product": "starpio",
            "agent": "video",
            "action": "launch_video",
            "payload": {},
            "critical": False,
        }
        mock_db.list_pending_tasks.return_value = [due_task]
        with patch("agents.launch.executor.dispatch_to_agent") as mock_dispatch, \
             patch("agents.launch.executor.send_alert") as mock_alert:
            mock_dispatch.side_effect = Exception("video render slow")
            executor.run()
        mock_alert.assert_not_called()

    def test_execute_no_tasks_returns_idle(self, mock_db, cfg):
        executor = LaunchExecutor(mock_db, cfg)
        mock_db.list_pending_tasks.return_value = []
        with patch("agents.launch.executor.dispatch_to_agent") as mock_dispatch:
            result = executor.run()
        mock_dispatch.assert_not_called()
        assert result["tasks_dispatched"] == 0

    def test_execute_result_has_required_keys(self, mock_db, cfg):
        executor = LaunchExecutor(mock_db, cfg)
        mock_db.list_pending_tasks.return_value = []
        result = executor.run()
        for key in ("tasks_dispatched", "tasks_failed", "tasks_completed"):
            assert key in result


# ---------------------------------------------------------------------------
# ProductHuntLaunch
# ---------------------------------------------------------------------------

class TestProductHuntLaunch:

    def test_generates_tagline(self, mock_db, cfg):
        ph = ProductHuntLaunch(mock_db, cfg)
        with patch("agents.launch.product_hunt.llm") as mock_llm, \
             patch("agents.launch.product_hunt.enqueue_social_posts"), \
             patch("agents.launch.product_hunt.send_ph_notification"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "tagline": "AI replies for every Google review — on autopilot",
                    "description": "Starpio watches your reviews and drafts responses...",
                    "maker_comment": "Hey PH! We built Starpio because...",
                    "first_comment": "To get started, connect your GBP...",
                    "hunter_message": "Hey [name], would love your support...",
                }))
            ]
            result = ph.orchestrate(product="starpio", launch_date=_LAUNCH_DATE)
        assert "tagline" in result
        assert len(result["tagline"]) > 0

    def test_generates_all_five_copy_pieces(self, mock_db, cfg):
        ph = ProductHuntLaunch(mock_db, cfg)
        with patch("agents.launch.product_hunt.llm") as mock_llm, \
             patch("agents.launch.product_hunt.enqueue_social_posts"), \
             patch("agents.launch.product_hunt.send_ph_notification"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "tagline": "tagline text",
                    "description": "description text",
                    "maker_comment": "maker comment",
                    "first_comment": "first comment",
                    "hunter_message": "hunter message",
                }))
            ]
            result = ph.orchestrate(product="starpio", launch_date=_LAUNCH_DATE)
        for key in ("tagline", "description", "maker_comment", "first_comment", "hunter_message"):
            assert key in result

    def test_schedules_social_support_posts(self, mock_db, cfg):
        ph = ProductHuntLaunch(mock_db, cfg)
        with patch("agents.launch.product_hunt.llm") as mock_llm, \
             patch("agents.launch.product_hunt.enqueue_social_posts") as mock_social, \
             patch("agents.launch.product_hunt.send_ph_notification"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "tagline": "t", "description": "d",
                    "maker_comment": "m", "first_comment": "f", "hunter_message": "h",
                }))
            ]
            ph.orchestrate(product="starpio", launch_date=_LAUNCH_DATE)
        mock_social.assert_called_once()

    def test_sends_ph_notification_to_dutch(self, mock_db, cfg):
        ph = ProductHuntLaunch(mock_db, cfg)
        with patch("agents.launch.product_hunt.llm") as mock_llm, \
             patch("agents.launch.product_hunt.enqueue_social_posts"), \
             patch("agents.launch.product_hunt.send_ph_notification") as mock_notify:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "tagline": "t", "description": "d",
                    "maker_comment": "m", "first_comment": "f", "hunter_message": "h",
                }))
            ]
            ph.orchestrate(product="starpio", launch_date=_LAUNCH_DATE)
        mock_notify.assert_called_once()

    def test_result_has_required_keys(self, mock_db, cfg):
        ph = ProductHuntLaunch(mock_db, cfg)
        with patch("agents.launch.product_hunt.llm") as mock_llm, \
             patch("agents.launch.product_hunt.enqueue_social_posts"), \
             patch("agents.launch.product_hunt.send_ph_notification"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "tagline": "t", "description": "d",
                    "maker_comment": "m", "first_comment": "f", "hunter_message": "h",
                }))
            ]
            result = ph.orchestrate(product="starpio", launch_date=_LAUNCH_DATE)
        for key in ("product", "tagline", "description", "maker_comment",
                    "first_comment", "hunter_message", "social_posts_queued"):
            assert key in result

    def test_tagline_under_60_chars(self, mock_db, cfg):
        ph = ProductHuntLaunch(mock_db, cfg)
        with patch("agents.launch.product_hunt.llm") as mock_llm, \
             patch("agents.launch.product_hunt.enqueue_social_posts"), \
             patch("agents.launch.product_hunt.send_ph_notification"):
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "tagline": "AI replies for every Google review — autopilot",
                    "description": "d", "maker_comment": "m",
                    "first_comment": "f", "hunter_message": "h",
                }))
            ]
            result = ph.orchestrate(product="starpio", launch_date=_LAUNCH_DATE)
        assert len(result["tagline"]) <= 60


# ---------------------------------------------------------------------------
# LaunchDebrief
# ---------------------------------------------------------------------------

class TestLaunchDebrief:

    def test_debrief_pulls_all_metric_categories(self, mock_db, cfg):
        debrief = LaunchDebrief(mock_db, cfg)
        with patch("agents.launch.debrief.llm") as mock_llm, \
             patch("agents.launch.debrief.fetch_launch_metrics") as mock_metrics, \
             patch("agents.launch.debrief.enqueue_voice_report"):
            mock_metrics.return_value = {
                "signups": 142,
                "revenue_delta": 3800,
                "social_engagement": 1240,
                "press_mentions": 3,
                "support_ticket_volume": 18,
            }
            mock_llm.complete.return_value.content = [
                MagicMock(text="Launch exceeded expectations. 142 signups in 7 days. "
                               "Revenue up $3,800. 3 press mentions. Recommend doubling down on outreach.")
            ]
            result = debrief.run(plan_id=str(uuid.uuid4()), product="starpio")
        mock_metrics.assert_called_once()
        assert result["signups"] == 142
        assert result["revenue_delta"] == 3800

    def test_debrief_llm_generates_narrative(self, mock_db, cfg):
        debrief = LaunchDebrief(mock_db, cfg)
        with patch("agents.launch.debrief.llm") as mock_llm, \
             patch("agents.launch.debrief.fetch_launch_metrics") as mock_metrics, \
             patch("agents.launch.debrief.enqueue_voice_report"):
            mock_metrics.return_value = {
                "signups": 50, "revenue_delta": 1200,
                "social_engagement": 400, "press_mentions": 0,
                "support_ticket_volume": 8,
            }
            mock_llm.complete.return_value.content = [MagicMock(text="Solid launch. 50 signups, low support volume.")]
            result = debrief.run(plan_id=str(uuid.uuid4()), product="starpio")
        assert "narrative" in result
        assert len(result["narrative"]) > 0
        mock_llm.complete.assert_called_once()

    def test_debrief_stores_results_to_db(self, mock_db, cfg):
        debrief = LaunchDebrief(mock_db, cfg)
        plan_id = str(uuid.uuid4())
        with patch("agents.launch.debrief.llm") as mock_llm, \
             patch("agents.launch.debrief.fetch_launch_metrics") as mock_metrics, \
             patch("agents.launch.debrief.enqueue_voice_report"):
            mock_metrics.return_value = {
                "signups": 100, "revenue_delta": 2500,
                "social_engagement": 800, "press_mentions": 1,
                "support_ticket_volume": 12,
            }
            mock_llm.complete.return_value.content = [MagicMock(text="Great launch.")]
            debrief.run(plan_id=plan_id, product="starpio")
        assert mock_db.save_result.call_count >= 5

    def test_debrief_delivers_to_voice_report(self, mock_db, cfg):
        debrief = LaunchDebrief(mock_db, cfg)
        with patch("agents.launch.debrief.llm") as mock_llm, \
             patch("agents.launch.debrief.fetch_launch_metrics") as mock_metrics, \
             patch("agents.launch.debrief.enqueue_voice_report") as mock_voice:
            mock_metrics.return_value = {
                "signups": 80, "revenue_delta": 2000,
                "social_engagement": 600, "press_mentions": 2,
                "support_ticket_volume": 10,
            }
            mock_llm.complete.return_value.content = [MagicMock(text="Good launch performance.")]
            debrief.run(plan_id=str(uuid.uuid4()), product="starpio")
        mock_voice.assert_called_once()

    def test_debrief_result_has_required_keys(self, mock_db, cfg):
        debrief = LaunchDebrief(mock_db, cfg)
        with patch("agents.launch.debrief.llm") as mock_llm, \
             patch("agents.launch.debrief.fetch_launch_metrics") as mock_metrics, \
             patch("agents.launch.debrief.enqueue_voice_report"):
            mock_metrics.return_value = {
                "signups": 0, "revenue_delta": 0,
                "social_engagement": 0, "press_mentions": 0,
                "support_ticket_volume": 0,
            }
            mock_llm.complete.return_value.content = [MagicMock(text="No data yet.")]
            result = debrief.run(plan_id=str(uuid.uuid4()), product="starpio")
        for key in ("product", "narrative", "signups", "revenue_delta",
                    "social_engagement", "press_mentions", "support_ticket_volume"):
            assert key in result

    def test_debrief_updates_plan_status_to_complete(self, mock_db, cfg):
        debrief = LaunchDebrief(mock_db, cfg)
        plan_id = str(uuid.uuid4())
        with patch("agents.launch.debrief.llm") as mock_llm, \
             patch("agents.launch.debrief.fetch_launch_metrics") as mock_metrics, \
             patch("agents.launch.debrief.enqueue_voice_report"):
            mock_metrics.return_value = {
                "signups": 60, "revenue_delta": 1500,
                "social_engagement": 500, "press_mentions": 1,
                "support_ticket_volume": 9,
            }
            mock_llm.complete.return_value.content = [MagicMock(text="Completed.")]
            debrief.run(plan_id=plan_id, product="starpio")
        mock_db.update_plan_status.assert_called_once_with(plan_id=plan_id, status="completed")


# ---------------------------------------------------------------------------
# LaunchAgent dispatch
# ---------------------------------------------------------------------------

class TestLaunchAgent:

    @pytest.fixture
    def agent(self, cfg):
        from agents.launch.main import LaunchAgent
        config = MagicMock(spec=AgentConfig)
        config.custom = cfg
        config.llm_system_prompt = ""
        config.poll_interval_seconds = 2
        with patch("agents.launch.main.LaunchDB"), \
             patch("agents.launch.main.LaunchPlanner"), \
             patch("agents.launch.main.LaunchExecutor"), \
             patch("agents.launch.main.ProductHuntLaunch"), \
             patch("agents.launch.main.LaunchDebrief"):
            return LaunchAgent("launch", config)

    def test_unknown_action_returns_error(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "launch_rocket"},
        )
        result = agent.handle(task)
        assert result.success is False
        assert "error" in result.output

    def test_plan_launch_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "plan_launch",
                "product": "starpio",
                "launch_type": "major_feature",
                "launch_date": "2026-07-01",
            },
        )
        agent._planner.plan.return_value = {
            "plan_id": str(uuid.uuid4()), "product": "starpio",
            "launch_type": "major_feature", "launch_date": "2026-07-01",
            "tasks": [], "task_count": 9,
        }
        result = agent.handle(task)
        assert result.success is True
        agent._planner.plan.assert_called_once()

    def test_execute_launch_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={"action": "execute_launch"},
        )
        agent._executor.run.return_value = {
            "tasks_dispatched": 3, "tasks_failed": 0, "tasks_completed": 3
        }
        result = agent.handle(task)
        assert result.success is True
        agent._executor.run.assert_called_once()

    def test_product_hunt_launch_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "product_hunt_launch",
                "product": "starpio",
                "launch_date": "2026-07-01",
            },
        )
        agent._product_hunt.orchestrate.return_value = {
            "product": "starpio", "tagline": "AI replies on autopilot",
            "description": "d", "maker_comment": "m",
            "first_comment": "f", "hunter_message": "h",
            "social_posts_queued": True,
        }
        result = agent.handle(task)
        assert result.success is True
        agent._product_hunt.orchestrate.assert_called_once()

    def test_launch_debrief_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "launch_debrief",
                "plan_id": str(uuid.uuid4()),
                "product": "starpio",
            },
        )
        agent._debrief.run.return_value = {
            "product": "starpio", "narrative": "Great launch.",
            "signups": 142, "revenue_delta": 3800,
            "social_engagement": 1200, "press_mentions": 3,
            "support_ticket_volume": 15,
        }
        result = agent.handle(task)
        assert result.success is True
        agent._debrief.run.assert_called_once()

    def test_plan_launch_missing_product_returns_error(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "plan_launch",
                "launch_type": "major_feature",
                "launch_date": "2026-07-01",
            },
        )
        result = agent.handle(task)
        assert result.success is False
        assert "error" in result.output

    def test_plan_launch_missing_date_returns_error(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.MARKETING,
            payload={
                "action": "plan_launch",
                "product": "starpio",
                "launch_type": "major_feature",
            },
        )
        result = agent.handle(task)
        assert result.success is False
        assert "error" in result.output

    def test_health_check_true_when_db_ok(self, agent):
        agent._db.list_pending_tasks.return_value = []
        assert agent.health_check() is True

    def test_health_check_false_on_db_error(self, agent):
        agent._db.list_pending_tasks.side_effect = Exception("db down")
        assert agent.health_check() is False
