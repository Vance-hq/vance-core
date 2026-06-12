"""Behavioral tests for the scaling agent."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CFG = {
    "prometheus_url": "http://prometheus:9090",
    "thresholds": {
        "cpu_warning_pct": 80.0,
        "cpu_warning_window_min": 5,
        "cpu_critical_pct": 95.0,
        "cpu_critical_window_min": 2,
        "memory_warning_pct": 85.0,
        "disk_warning_pct": 80.0,
        "disk_critical_pct": 90.0,
    },
    "capacity_limits": {
        "cpu_pct": 90.0,
        "memory_pct": 90.0,
        "disk_pct": 85.0,
    },
    "known_processes": ["python3", "node", "nginx", "postgres"],
}


def _task(action: str, **payload):
    from shared.types import AgentCapability, Task
    return Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.SCALING,
        payload={"action": action, **payload},
    )


def _agent():
    from agents._base import AgentConfig
    from agents.scaling.main import ScalingAgent

    raw = {
        "agent_name": "scaling",
        "enabled": True,
        "poll_interval_seconds": 60.0,
        "max_retries": 3,
        "llm_system_prompt": "",
        "custom": _CFG,
    }
    config = AgentConfig(**raw)
    with (
        patch("agents.scaling.main.ScalingDB"),
        patch("agents.scaling.main.ResourceCollector"),
        patch("agents.scaling.main.ThresholdChecker"),
        patch("agents.scaling.main.AutoRemediation"),
        patch("agents.scaling.main.CapacityPlanner"),
        patch("agents.scaling.main.BaseAgent.__init__", lambda *a, **kw: None),
    ):
        agent = ScalingAgent.__new__(ScalingAgent)
        agent.agent_name = "scaling"
        agent.config = config
        agent._db = MagicMock()
        agent._collector = MagicMock()
        agent._checker = MagicMock()
        agent._remediation = MagicMock()
        agent._planner = MagicMock()
        agent._dispatch = {
            "resource_monitor": agent._resource_monitor,
            "alert_threshold": agent._alert_threshold,
            "auto_remediate": agent._auto_remediate,
            "capacity_plan": agent._capacity_plan,
        }
        return agent


# ---------------------------------------------------------------------------
# ScalingAgent — routing
# ---------------------------------------------------------------------------

class TestScalingAgentRouting:
    def test_unknown_action_returns_failure(self):
        agent = _agent()
        result = agent.handle(_task("nonexistent"))
        assert result.success is False
        assert "unknown action" in result.error

    def test_resource_monitor_routes_correctly(self):
        agent = _agent()
        agent._collector.collect.return_value = {"host": {}, "containers": []}
        result = agent.handle(_task("resource_monitor"))
        assert result.success is True
        agent._collector.collect.assert_called_once()

    def test_alert_threshold_routes_correctly(self):
        agent = _agent()
        agent._collector.snapshot.return_value = {"host": {"cpu_pct": 50.0}, "containers": []}
        agent._checker.check.return_value = []
        result = agent.handle(_task("alert_threshold"))
        assert result.success is True
        agent._checker.check.assert_called_once()

    def test_auto_remediate_routes_correctly(self):
        agent = _agent()
        agent._remediation.remediate.return_value = {"outcome": "success"}
        result = agent.handle(_task("auto_remediate", trigger="memory_pct", value=90.0))
        assert result.success is True
        agent._remediation.remediate.assert_called_once_with("memory_pct", 90.0)

    def test_capacity_plan_routes_correctly(self):
        agent = _agent()
        agent._planner.plan.return_value = {"projections": {}}
        result = agent.handle(_task("capacity_plan"))
        assert result.success is True
        agent._planner.plan.assert_called_once()

    def test_exception_in_handler_returns_failure(self):
        agent = _agent()
        agent._collector.collect.side_effect = RuntimeError("psutil unavailable")
        result = agent.handle(_task("resource_monitor"))
        assert result.success is False
        assert "psutil unavailable" in result.error

    def test_auto_remediate_defaults_value_to_zero(self):
        agent = _agent()
        agent._remediation.remediate.return_value = {"outcome": "no_action"}
        agent.handle(_task("auto_remediate", trigger="cpu_pct"))
        agent._remediation.remediate.assert_called_once_with("cpu_pct", 0.0)


# ---------------------------------------------------------------------------
# ScalingAgent — health_check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_check_true_when_db_ok(self):
        agent = _agent()
        agent._db.get_recent_events.return_value = []
        assert agent.health_check() is True

    def test_health_check_false_when_db_fails(self):
        agent = _agent()
        agent._db.get_recent_events.side_effect = Exception("db down")
        assert agent.health_check() is False


# ---------------------------------------------------------------------------
# ResourceCollector
# ---------------------------------------------------------------------------

class TestResourceCollector:
    def _collector(self, db=None):
        from agents.scaling.resource_collector import ResourceCollector
        return ResourceCollector(_CFG, db or MagicMock())

    def test_collect_stores_host_metrics(self):
        db = MagicMock()
        with (
            patch("agents.scaling.resource_collector.psutil") as mock_psutil,
            patch("agents.scaling.resource_collector.httpx.HTTPTransport"),
            patch("agents.scaling.resource_collector.httpx.Client") as MockClient,
        ):
            mock_psutil.cpu_percent.return_value = 45.0
            mock_psutil.virtual_memory.return_value = MagicMock(percent=60.0)
            mock_psutil.disk_usage.return_value = MagicMock(percent=55.0)
            mock_psutil.net_io_counters.return_value = MagicMock(bytes_sent=1000, bytes_recv=2000)
            # Docker socket: return empty container list
            ctx = MockClient.return_value.__enter__.return_value
            ctx.get.return_value = MagicMock(status_code=200)
            ctx.get.return_value.json.return_value = []
            ctx.get.return_value.raise_for_status = MagicMock()
            collector = self._collector(db)
            result = collector.collect()
        assert result["host"]["cpu_pct"] == 45.0
        assert result["host"]["memory_pct"] == 60.0
        assert result["host"]["disk_pct"] == 55.0
        db.bulk_insert_metrics.assert_called_once()

    def test_collect_includes_timestamp(self):
        db = MagicMock()
        with (
            patch("agents.scaling.resource_collector.psutil") as mock_psutil,
            patch("agents.scaling.resource_collector.httpx.HTTPTransport"),
            patch("agents.scaling.resource_collector.httpx.Client") as MockClient,
        ):
            mock_psutil.cpu_percent.return_value = 30.0
            mock_psutil.virtual_memory.return_value = MagicMock(percent=40.0)
            mock_psutil.disk_usage.return_value = MagicMock(percent=50.0)
            mock_psutil.net_io_counters.return_value = MagicMock(bytes_sent=0, bytes_recv=0)
            ctx = MockClient.return_value.__enter__.return_value
            ctx.get.return_value = MagicMock()
            ctx.get.return_value.json.return_value = []
            ctx.get.return_value.raise_for_status = MagicMock()
            collector = self._collector(db)
            result = collector.collect()
        assert "recorded_at" in result
        assert "T" in result["recorded_at"]  # ISO format

    def test_docker_unavailable_still_returns_host_metrics(self):
        db = MagicMock()
        with (
            patch("agents.scaling.resource_collector.psutil") as mock_psutil,
            patch("agents.scaling.resource_collector.httpx.HTTPTransport") as MockTransport,
            patch("agents.scaling.resource_collector.httpx.Client") as MockClient,
        ):
            mock_psutil.cpu_percent.return_value = 50.0
            mock_psutil.virtual_memory.return_value = MagicMock(percent=70.0)
            mock_psutil.disk_usage.return_value = MagicMock(percent=60.0)
            mock_psutil.net_io_counters.return_value = MagicMock(bytes_sent=0, bytes_recv=0)
            MockClient.return_value.__enter__.side_effect = Exception("socket unavailable")
            collector = self._collector(db)
            result = collector.collect()
        assert result["host"]["cpu_pct"] == 50.0
        assert result["containers"] == []

    def test_parse_cpu_pct_calculates_correctly(self):
        from agents.scaling.resource_collector import ResourceCollector
        stat = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200_000_000, "percpu_usage": [0, 0]},
                "system_cpu_usage": 1_000_000_000,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100_000_000},
                "system_cpu_usage": 900_000_000,
            },
        }
        pct = ResourceCollector._parse_cpu_pct(stat)
        # delta=100M, sys_delta=100M, cpus=2 → 100M/100M * 2 * 100 = 200%
        assert pct == 200.0

    def test_parse_cpu_pct_returns_zero_on_bad_data(self):
        from agents.scaling.resource_collector import ResourceCollector
        assert ResourceCollector._parse_cpu_pct({}) == 0.0

    def test_parse_mem_pct_subtracts_cache(self):
        from agents.scaling.resource_collector import ResourceCollector
        stat = {
            "memory_stats": {
                "usage": 500_000_000,
                "limit": 1_000_000_000,
                "stats": {"cache": 100_000_000},
            }
        }
        pct = ResourceCollector._parse_mem_pct(stat)
        # (500M - 100M) / 1000M * 100 = 40%
        assert pct == 40.0

    def test_snapshot_does_not_write_to_db(self):
        db = MagicMock()
        with (
            patch("agents.scaling.resource_collector.psutil") as mock_psutil,
            patch("agents.scaling.resource_collector.httpx.HTTPTransport"),
            patch("agents.scaling.resource_collector.httpx.Client") as MockClient,
        ):
            mock_psutil.cpu_percent.return_value = 30.0
            mock_psutil.virtual_memory.return_value = MagicMock(percent=40.0)
            mock_psutil.disk_usage.return_value = MagicMock(percent=50.0)
            mock_psutil.net_io_counters.return_value = MagicMock(bytes_sent=0, bytes_recv=0)
            ctx = MockClient.return_value.__enter__.return_value
            ctx.get.return_value = MagicMock()
            ctx.get.return_value.json.return_value = []
            ctx.get.return_value.raise_for_status = MagicMock()
            collector = self._collector(db)
            collector.snapshot()
        db.bulk_insert_metrics.assert_not_called()


# ---------------------------------------------------------------------------
# ThresholdChecker
# ---------------------------------------------------------------------------

class TestThresholdChecker:
    def _checker(self, db=None):
        from agents.scaling.threshold_checker import ThresholdChecker
        return ThresholdChecker(_CFG, db or MagicMock())

    def _snapshot(self, cpu=50.0, memory=50.0, disk=50.0):
        return {"host": {"cpu_pct": cpu, "memory_pct": memory, "disk_pct": disk}}

    def test_no_alerts_when_all_metrics_normal(self):
        db = MagicMock()
        checker = self._checker(db)
        result = checker.check(self._snapshot())
        assert result == []

    def test_cpu_warning_fires_when_sustained(self):
        db = MagicMock()
        db.get_recent_metrics.return_value = [
            {"value": 82.0}, {"value": 83.0}, {"value": 81.0}
        ]
        with patch("agents.scaling.threshold_checker.TaskQueue"):
            checker = self._checker(db)
            alerts = checker.check(self._snapshot(cpu=82.0))
        cpu_alerts = [a for a in alerts if a["metric"] == "cpu_pct"]
        assert len(cpu_alerts) == 1
        assert cpu_alerts[0]["level"] == "WARNING"

    def test_cpu_critical_fires_when_sustained_above_95(self):
        db = MagicMock()
        db.get_recent_metrics.return_value = [{"value": 96.0}, {"value": 97.0}]
        with patch("agents.scaling.threshold_checker.TaskQueue") as MockQueue:
            checker = self._checker(db)
            alerts = checker.check(self._snapshot(cpu=96.0))
        critical = [a for a in alerts if a["level"] == "CRITICAL"]
        assert len(critical) == 1
        assert critical[0]["metric"] == "cpu_pct"

    def test_cpu_critical_triggers_voice_alert(self):
        db = MagicMock()
        db.get_recent_metrics.return_value = [{"value": 96.0}]
        with patch("agents.scaling.threshold_checker.TaskQueue") as MockQueue:
            checker = self._checker(db)
            checker.check(self._snapshot(cpu=96.0))
        push_calls = MockQueue.return_value.push.call_args_list
        agents = [c[1]["agent"] for c in push_calls]
        assert "voice" in agents

    def test_cpu_critical_triggers_auto_remediation(self):
        db = MagicMock()
        db.get_recent_metrics.return_value = [{"value": 96.0}]
        with patch("agents.scaling.threshold_checker.TaskQueue") as MockQueue:
            checker = self._checker(db)
            checker.check(self._snapshot(cpu=96.0))
        push_calls = MockQueue.return_value.push.call_args_list
        agents = [c[1]["agent"] for c in push_calls]
        assert "scaling" in agents

    def test_cpu_no_alert_when_not_sustained(self):
        db = MagicMock()
        # Only one reading at warning level — not sustained for 5 min
        db.get_recent_metrics.return_value = []
        checker = self._checker(db)
        alerts = checker.check(self._snapshot(cpu=82.0))
        assert alerts == []

    def test_memory_warning_fires_at_threshold(self):
        db = MagicMock()
        with patch("agents.scaling.threshold_checker.TaskQueue"):
            checker = self._checker(db)
            alerts = checker.check(self._snapshot(memory=86.0))
        mem_alerts = [a for a in alerts if a["metric"] == "memory_pct"]
        assert len(mem_alerts) == 1
        assert mem_alerts[0]["level"] == "WARNING"

    def test_memory_no_alert_below_threshold(self):
        db = MagicMock()
        checker = self._checker(db)
        alerts = checker.check(self._snapshot(memory=84.0))
        assert not any(a["metric"] == "memory_pct" for a in alerts)

    def test_disk_warning_fires_at_80_pct(self):
        db = MagicMock()
        with patch("agents.scaling.threshold_checker.TaskQueue"):
            checker = self._checker(db)
            alerts = checker.check(self._snapshot(disk=81.0))
        disk_alerts = [a for a in alerts if a["metric"] == "disk_pct"]
        assert disk_alerts[0]["level"] == "WARNING"

    def test_disk_critical_fires_at_90_pct(self):
        db = MagicMock()
        with patch("agents.scaling.threshold_checker.TaskQueue") as MockQueue:
            checker = self._checker(db)
            alerts = checker.check(self._snapshot(disk=91.0))
        disk_alerts = [a for a in alerts if a["metric"] == "disk_pct"]
        assert disk_alerts[0]["level"] == "CRITICAL"

    def test_disk_critical_triggers_voice_and_remediation(self):
        db = MagicMock()
        with patch("agents.scaling.threshold_checker.TaskQueue") as MockQueue:
            checker = self._checker(db)
            checker.check(self._snapshot(disk=91.0))
        agents_notified = {c[1]["agent"] for c in MockQueue.return_value.push.call_args_list}
        assert "voice" in agents_notified
        assert "scaling" in agents_notified

    def test_warning_added_to_daily_brief(self):
        db = MagicMock()
        with patch("agents.scaling.threshold_checker.TaskQueue") as MockQueue:
            checker = self._checker(db)
            checker.check(self._snapshot(memory=87.0))
        push_calls = MockQueue.return_value.push.call_args_list
        reporting_calls = [c for c in push_calls if c[1]["agent"] == "reporting"]
        assert len(reporting_calls) == 1
        assert reporting_calls[0][1]["payload"]["action"] == "add_to_brief"

    def test_sustained_above_returns_false_when_no_data(self):
        db = MagicMock()
        db.get_recent_metrics.return_value = []
        checker = self._checker(db)
        assert checker._sustained_above("cpu_pct", 80.0, 5) is False

    def test_sustained_above_returns_false_when_not_all_exceed(self):
        db = MagicMock()
        db.get_recent_metrics.return_value = [{"value": 85.0}, {"value": 79.0}]
        checker = self._checker(db)
        assert checker._sustained_above("cpu_pct", 80.0, 5) is False

    def test_sustained_above_returns_true_when_all_exceed(self):
        db = MagicMock()
        db.get_recent_metrics.return_value = [{"value": 82.0}, {"value": 83.0}]
        checker = self._checker(db)
        assert checker._sustained_above("cpu_pct", 80.0, 5) is True


# ---------------------------------------------------------------------------
# AutoRemediation
# ---------------------------------------------------------------------------

class TestAutoRemediation:
    def _rem(self, db=None):
        from agents.scaling.auto_remediation import AutoRemediation
        return AutoRemediation(_CFG, db or MagicMock())

    def test_unknown_trigger_returns_no_action(self):
        db = MagicMock()
        rem = self._rem(db)
        result = rem.remediate("unknown_metric", 100.0)
        assert result["outcome"] == "no_action"

    def test_high_memory_restarts_top_container(self):
        db = MagicMock()
        rem = self._rem(db)
        with (
            patch("agents.scaling.auto_remediation.httpx.HTTPTransport"),
            patch("agents.scaling.auto_remediation.httpx.Client") as MockClient,
        ):
            ctx = MockClient.return_value.__enter__.return_value
            # list containers
            ctx.get.return_value = MagicMock()
            ctx.get.return_value.raise_for_status = MagicMock()
            ctx.get.return_value.json.side_effect = [
                [{"Id": "abc123", "Names": ["/web"]}],  # container list
                {  # stats for abc123
                    "memory_stats": {
                        "usage": 900_000_000,
                        "limit": 1_000_000_000,
                        "stats": {"cache": 0},
                    }
                },
            ]
            ctx.post.return_value = MagicMock()
            ctx.post.return_value.raise_for_status = MagicMock()
            result = rem.remediate("memory_pct", 92.0)
        assert result["outcome"] == "success"
        assert "restart_container" in result["action_taken"]

    def test_high_memory_no_container_found(self):
        db = MagicMock()
        rem = self._rem(db)
        with patch.object(rem, "_find_top_memory_container", return_value=None):
            result = rem.remediate("memory_pct", 90.0)
        assert result["outcome"] == "no_container_found"

    def test_high_disk_runs_log_prune_and_docker_prune(self):
        db = MagicMock()
        rem = self._rem(db)
        with (
            patch("agents.scaling.auto_remediation.subprocess.run") as mock_run,
            patch("agents.scaling.auto_remediation.psutil") as mock_psutil,
        ):
            mock_psutil.disk_usage.return_value = MagicMock(percent=75.0)
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = rem.remediate("disk_pct", 85.0)
        assert result["outcome"] == "success"
        assert result["action_taken"] == "prune_logs_and_images"
        assert mock_run.call_count >= 2  # find + docker image prune

    def test_high_disk_includes_before_and_after_usage(self):
        db = MagicMock()
        rem = self._rem(db)
        with (
            patch("agents.scaling.auto_remediation.subprocess.run"),
            patch("agents.scaling.auto_remediation.psutil") as mock_psutil,
        ):
            mock_psutil.disk_usage.return_value = MagicMock(percent=72.0)
            result = rem.remediate("disk_pct", 85.0)
        assert "disk_before_pct" in result["details"]
        assert "disk_after_pct" in result["details"]

    def test_high_cpu_identifies_top_process(self):
        db = MagicMock()
        rem = self._rem(db)
        with patch("agents.scaling.auto_remediation.psutil") as mock_psutil:
            mock_proc = MagicMock()
            mock_proc.pid = 1234
            mock_proc.name.return_value = "python3"
            mock_proc.cpu_percent.return_value = 85.0
            mock_psutil.process_iter.return_value = [mock_proc]
            result = rem.remediate("cpu_pct", 96.0)
        assert result["outcome"] == "success"
        assert result["details"]["top_process"]["name"] == "python3"

    def test_high_cpu_flags_unexpected_process(self):
        db = MagicMock()
        rem = self._rem(db)
        with (
            patch("agents.scaling.auto_remediation.psutil") as mock_psutil,
            patch("agents.scaling.auto_remediation.TaskQueue") as MockQueue,
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 9999
            mock_proc.name.return_value = "malicious_script"
            mock_proc.cpu_percent.return_value = 95.0
            mock_psutil.process_iter.return_value = [mock_proc]
            result = rem.remediate("cpu_pct", 96.0)
        assert result["details"]["unexpected"] is True
        MockQueue.return_value.push.assert_called_once()

    def test_high_cpu_known_process_not_flagged(self):
        db = MagicMock()
        rem = self._rem(db)
        with (
            patch("agents.scaling.auto_remediation.psutil") as mock_psutil,
            patch("agents.scaling.auto_remediation.TaskQueue") as MockQueue,
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 100
            mock_proc.name.return_value = "python3"
            mock_proc.cpu_percent.return_value = 90.0
            mock_psutil.process_iter.return_value = [mock_proc]
            result = rem.remediate("cpu_pct", 92.0)
        assert result["details"]["unexpected"] is False
        MockQueue.return_value.push.assert_not_called()

    def test_all_remediations_logged_to_db(self):
        db = MagicMock()
        rem = self._rem(db)
        with (
            patch("agents.scaling.auto_remediation.subprocess.run"),
            patch("agents.scaling.auto_remediation.psutil") as mock_psutil,
        ):
            mock_psutil.disk_usage.return_value = MagicMock(percent=70.0)
            rem.remediate("disk_pct", 85.0)
        db.insert_event.assert_called_once()
        call_kwargs = db.insert_event.call_args[1]
        assert call_kwargs["trigger"] == "disk_pct"


# ---------------------------------------------------------------------------
# CapacityPlanner
# ---------------------------------------------------------------------------

class TestCapacityPlanner:
    def _planner(self, db=None):
        from agents.scaling.capacity_planner import CapacityPlanner
        return CapacityPlanner(_CFG, db or MagicMock())

    def _history(self, start_pct: float, end_pct: float, n: int = 30) -> list[dict]:
        """Generate synthetic metric history from start_pct to end_pct over n points."""
        step = (end_pct - start_pct) / max(n - 1, 1)
        return [{"value": start_pct + i * step} for i in range(n)]

    def test_insufficient_data_returns_status(self):
        db = MagicMock()
        db.get_metric_history.return_value = [{"value": 50.0}]  # only 1 point
        planner = self._planner(db)
        with patch("agents.scaling.capacity_planner.TaskQueue"):
            result = planner.plan()
        for metric in ["cpu_pct", "memory_pct", "disk_pct"]:
            assert result["projections"][metric]["status"] == "insufficient_data"

    def test_stable_metric_shows_stable_status(self):
        db = MagicMock()
        # Flat history — zero growth
        history = [{"value": 40.0}] * 30
        db.get_metric_history.return_value = history
        planner = self._planner(db)
        with patch("agents.scaling.capacity_planner.TaskQueue"):
            result = planner.plan()
        # All metrics return same history
        for metric, proj in result["projections"].items():
            assert proj["status"] in ("stable_or_declining", "ok")

    def test_growing_metric_projects_days_until_limit(self):
        db = MagicMock()
        # Growing from 50% to 80% over 90 days → ~0.33%/day
        history = self._history(50.0, 80.0, 90)
        db.get_metric_history.return_value = history
        planner = self._planner(db)
        with patch("agents.scaling.capacity_planner.TaskQueue"):
            result = planner.plan()
        cpu_proj = result["projections"]["cpu_pct"]
        assert cpu_proj["days_until_limit"] is not None
        assert cpu_proj["growth_per_day"] > 0

    def test_fast_growth_triggers_alert(self):
        db = MagicMock()
        # Growing from 80% to 89% over 10 days → hits 90% limit quickly
        history = self._history(80.0, 89.0, 10)
        db.get_metric_history.return_value = history
        planner = self._planner(db)
        with patch("agents.scaling.capacity_planner.TaskQueue") as MockQueue:
            result = planner.plan()
        assert len(result["alerts"]) > 0
        MockQueue.return_value.push.assert_called_once()

    def test_fast_growth_alert_sent_to_reporting(self):
        db = MagicMock()
        history = self._history(80.0, 89.0, 10)
        db.get_metric_history.return_value = history
        planner = self._planner(db)
        with patch("agents.scaling.capacity_planner.TaskQueue") as MockQueue:
            planner.plan()
        call_kwargs = MockQueue.return_value.push.call_args[1]
        assert call_kwargs["agent"] == "reporting"

    def test_slow_growth_does_not_alert(self):
        db = MagicMock()
        # Barely growing — will take >90 days to hit 90%
        history = self._history(40.0, 45.0, 90)
        db.get_metric_history.return_value = history
        planner = self._planner(db)
        with patch("agents.scaling.capacity_planner.TaskQueue") as MockQueue:
            result = planner.plan()
        assert result["alerts"] == []
        MockQueue.return_value.push.assert_not_called()

    def test_alert_includes_recommendation(self):
        db = MagicMock()
        history = self._history(80.0, 89.0, 10)
        db.get_metric_history.return_value = history
        planner = self._planner(db)
        with patch("agents.scaling.capacity_planner.TaskQueue"):
            result = planner.plan()
        for alert in result["alerts"]:
            assert "recommendation" in alert
            assert len(alert["recommendation"]) > 0

    def test_plan_logs_scaling_event(self):
        db = MagicMock()
        history = [{"value": 40.0}] * 30
        db.get_metric_history.return_value = history
        planner = self._planner(db)
        with patch("agents.scaling.capacity_planner.TaskQueue"):
            planner.plan()
        db.insert_event.assert_called_once()
        call_kwargs = db.insert_event.call_args[1]
        assert call_kwargs["trigger"] == "scheduled_plan"

    def test_linear_regression_on_perfect_line(self):
        from agents.scaling.capacity_planner import CapacityPlanner
        planner = CapacityPlanner(_CFG, MagicMock())
        # Perfect line: 0, 2, 4, 6, 8 → slope = 2
        history = [{"value": float(i * 2)} for i in range(5)]
        slope, current = planner._linear_regression(history)
        assert abs(slope - 2.0) < 0.01
        assert current == 8.0

    def test_recommendation_contains_metric_name(self):
        from agents.scaling.capacity_planner import CapacityPlanner
        planner = CapacityPlanner(_CFG, MagicMock())
        rec = planner._recommendation("cpu_pct", 30.0)
        assert "CPU" in rec or "cpu" in rec.lower()

    def test_report_includes_metadata(self):
        db = MagicMock()
        history = [{"value": 40.0}] * 30
        db.get_metric_history.return_value = history
        planner = self._planner(db)
        with patch("agents.scaling.capacity_planner.TaskQueue"):
            result = planner.plan()
        assert result["analysis_days"] == 90
        assert result["horizon_days"] == 90
        assert "generated_at" in result


# ---------------------------------------------------------------------------
# ScalingDB
# ---------------------------------------------------------------------------

class TestScalingDB:
    def _db(self):
        from agents.scaling.db import ScalingDB
        return ScalingDB()

    def _mock_conn(self, fetchone_val=None):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = fetchone_val
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        return mock_conn, mock_cur

    def test_insert_metric_executes_sql(self):
        db = self._db()
        mock_conn, mock_cur = self._mock_conn((str(uuid.uuid4()),))
        with patch("agents.scaling.db.get_db", return_value=mock_conn):
            record_id = db.insert_metric(metric_name="cpu_pct", value=75.0)
        assert record_id is not None
        mock_cur.execute.assert_called_once()

    def test_bulk_insert_metrics_skips_empty_list(self):
        db = self._db()
        with patch("agents.scaling.db.get_db") as mock_get_db:
            db.bulk_insert_metrics([])
        mock_get_db.assert_not_called()

    def test_insert_event_executes_sql(self):
        db = self._db()
        mock_conn, mock_cur = self._mock_conn((str(uuid.uuid4()),))
        with patch("agents.scaling.db.get_db", return_value=mock_conn):
            record_id = db.insert_event(
                trigger="high_cpu",
                action_taken="identify_top_process",
                outcome="success",
            )
        assert record_id is not None

    def test_get_recent_events_returns_list(self):
        db = self._db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = []
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        with patch("agents.scaling.db.get_db", return_value=mock_conn):
            result = db.get_recent_events(hours=24)
        assert isinstance(result, list)

    def test_get_average_metric_returns_none_when_empty(self):
        db = self._db()
        mock_conn, mock_cur = self._mock_conn((None,))
        with patch("agents.scaling.db.get_db", return_value=mock_conn):
            result = db.get_average_metric("cpu_pct", minutes=5)
        assert result is None


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------

class TestCeleryTasks:
    def test_collect_resources_task_registered(self):
        import agents.scaling.tasks as tasks_mod
        assert hasattr(tasks_mod, "collect_resources")

    def test_check_thresholds_task_registered(self):
        import agents.scaling.tasks as tasks_mod
        assert hasattr(tasks_mod, "check_thresholds")

    def test_monthly_capacity_plan_task_registered(self):
        import agents.scaling.tasks as tasks_mod
        assert hasattr(tasks_mod, "monthly_capacity_plan")

    def test_remediate_resource_task_registered(self):
        import agents.scaling.tasks as tasks_mod
        assert hasattr(tasks_mod, "remediate_resource")

    def test_task_helper_builds_scaling_task(self):
        import agents.scaling.tasks as tasks_mod
        from shared.types import AgentCapability
        t = tasks_mod._task("resource_monitor")
        assert t.agent == AgentCapability.SCALING
        assert t.payload["action"] == "resource_monitor"

    def test_task_helper_passes_extra_payload(self):
        import agents.scaling.tasks as tasks_mod
        t = tasks_mod._task("auto_remediate", trigger="disk_pct", value=88.0)
        assert t.payload["trigger"] == "disk_pct"
        assert t.payload["value"] == 88.0

    def test_agent_factory_returns_scaling_agent(self):
        import agents.scaling.tasks as tasks_mod
        from agents.scaling.main import ScalingAgent
        with (
            patch("agents._base.config.AgentConfig.load") as mock_load,
            patch("agents.scaling.main.ScalingDB"),
            patch("agents.scaling.main.ResourceCollector"),
            patch("agents.scaling.main.ThresholdChecker"),
            patch("agents.scaling.main.AutoRemediation"),
            patch("agents.scaling.main.CapacityPlanner"),
            patch("agents._base.agent.redis.Redis"),
        ):
            cfg = MagicMock()
            cfg.custom = {}
            mock_load.return_value = cfg
            agent = tasks_mod._agent()
        assert isinstance(agent, ScalingAgent)


# ---------------------------------------------------------------------------
# AgentCapability enum
# ---------------------------------------------------------------------------

class TestAgentCapabilityEnum:
    def test_scaling_capability_exists(self):
        from shared.types import AgentCapability
        assert AgentCapability.SCALING == "scaling"

    def test_scaling_used_in_task(self):
        from shared.types import AgentCapability, Task
        t = Task(
            id="test-id",
            agent=AgentCapability.SCALING,
            payload={"action": "resource_monitor"},
        )
        assert t.agent == AgentCapability.SCALING
