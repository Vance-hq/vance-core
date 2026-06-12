"""Deploy agent unit tests — no external services, no live subprocesses."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from subprocess import CompletedProcess
from unittest.mock import MagicMock, call, patch

import pytest

from agents._base import AgentConfig
from agents.deploy.db import DeployDB
from agents.deploy.pipeline_runner import CIPipelineRunner
from agents.deploy.promoter import Promoter
from agents.deploy.rollback_handler import RollbackHandler
from agents.deploy.env_syncer import EnvSyncer
from agents.deploy.release_notes import ReleaseNotesGenerator
from shared.types import AgentCapability, Task, TaskResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proc(returncode: int = 0, stdout: str = "ok", stderr: str = "") -> CompletedProcess:
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _deployment(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "repo": "vance-app",
        "environment": "production",
        "version": "abc1234",
        "deployed_at": datetime.now(timezone.utc),
        "status": "success",
        "deployed_by_task_id": str(uuid.uuid4()),
    }
    if overrides:
        base.update(overrides)
    return base


def _pipeline_run(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "repo": "vance-app",
        "pr_number": 42,
        "branch": "feat/new-thing",
        "build_id": "build_abc",
        "status": "success",
        "steps": [],
        "duration_ms": 90000,
    }
    if overrides:
        base.update(overrides)
    return base


def _task(action: str, payload: dict | None = None) -> Task:
    p = {"action": action}
    if payload:
        p.update(payload)
    return Task(id=str(uuid.uuid4()), agent=AgentCapability.DEPLOY, payload=p)


def _cfg() -> dict:
    return {
        "repos_path": "/tmp/repos",
        "subprocess_timeout_s": 300,
        "deploy_poll_interval_s": 0,
        "github_token": "ghp_test",
        "github_org": "vance-hq",
        "staging_db_url": "postgresql://staging/testdb",
        "blackout_windows": [],
        "repos": {
            "vance-app": {
                "type": "node",
                "vercel_project_id": "prj_abc",
                "default_branch": "main",
                "staging_url": "https://staging.vance.so",
                "seed_cmd": "npm run db:seed",
            }
        },
    }


@pytest.fixture
def mock_db():
    db = MagicMock(spec=DeployDB)
    db.save_pipeline_run.return_value = str(uuid.uuid4())
    db.save_deployment.return_value = str(uuid.uuid4())
    db.get_latest_pipeline_run.return_value = _pipeline_run()
    db.get_last_successful_deployment.return_value = _deployment()
    db.get_previous_deployment.return_value = _deployment({"version": "prev_version_xyz"})
    return db


@pytest.fixture
def cfg():
    return _cfg()


# ---------------------------------------------------------------------------
# TestDeployDB
# ---------------------------------------------------------------------------

class TestDeployDB:

    def _conn_mock(self, fetchone=None, fetchall=None):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = fetchone
        cur.fetchall.return_value = fetchall or []
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn, cur

    def test_save_pipeline_run_returns_id(self):
        db = DeployDB()
        run_id = str(uuid.uuid4())
        conn, cur = self._conn_mock(fetchone=(run_id,))
        with patch("agents.deploy.db.get_db", return_value=conn):
            result = db.save_pipeline_run(repo="vance-app", pr_number=42, branch="feat/x")
        assert result == run_id

    def test_update_pipeline_run_sets_completed_at_on_terminal_status(self):
        db = DeployDB()
        conn, cur = self._conn_mock()
        run_id = str(uuid.uuid4())
        with patch("agents.deploy.db.get_db", return_value=conn):
            db.update_pipeline_run(run_id=run_id, status="success", duration_ms=5000)
        sql = cur.execute.call_args[0][0]
        assert "completed_at" in sql

    def test_get_latest_pipeline_run_returns_none_when_no_rows(self):
        db = DeployDB()
        conn, cur = self._conn_mock(fetchone=None)
        with patch("agents.deploy.db.get_db", return_value=conn):
            result = db.get_latest_pipeline_run("vance-app")
        assert result is None

    def test_save_deployment_returns_id(self):
        db = DeployDB()
        dep_id = str(uuid.uuid4())
        conn, cur = self._conn_mock(fetchone=(dep_id,))
        with patch("agents.deploy.db.get_db", return_value=conn):
            result = db.save_deployment(
                repo="vance-app",
                environment="production",
                version="build_abc",
                status="pending",
            )
        assert result == dep_id

    def test_get_last_successful_deployment_filters_by_status(self):
        db = DeployDB()
        conn, cur = self._conn_mock(fetchone=None)
        with patch("agents.deploy.db.get_db", return_value=conn):
            db.get_last_successful_deployment("vance-app", "production")
        sql = cur.execute.call_args[0][0]
        assert "status = 'success'" in sql

    def test_get_previous_deployment_excludes_current_version(self):
        db = DeployDB()
        conn, cur = self._conn_mock(fetchone=None)
        with patch("agents.deploy.db.get_db", return_value=conn):
            db.get_previous_deployment("vance-app", "production", "current_ver")
        sql, params = cur.execute.call_args[0]
        assert "version != %s" in sql
        assert "current_ver" in params

    def test_update_deployment_persists_status(self):
        db = DeployDB()
        conn, cur = self._conn_mock()
        dep_id = str(uuid.uuid4())
        with patch("agents.deploy.db.get_db", return_value=conn):
            db.update_deployment(deployment_id=dep_id, status="success")
        sql, params = cur.execute.call_args[0]
        assert "UPDATE deployments" in sql
        assert "success" in params


# ---------------------------------------------------------------------------
# TestCIPipelineRunner
# ---------------------------------------------------------------------------

class TestCIPipelineRunner:

    def test_run_returns_run_id_and_steps(self, mock_db, cfg):
        runner = CIPipelineRunner(mock_db, cfg)
        with patch.object(runner, "_run_step", return_value={"name": "lint", "success": True, "output": "", "duration_ms": 100}), \
             patch("agents.deploy.pipeline_runner._enqueue_dev_notification"), \
             patch.object(runner, "_post_pr_status"):
            result = runner.run(repo="vance-app", pr_number=42, branch="feat/x")

        assert "run_id" in result
        assert "steps" in result
        assert isinstance(result["steps"], list)

    def test_run_saves_pipeline_run_to_db(self, mock_db, cfg):
        runner = CIPipelineRunner(mock_db, cfg)
        with patch.object(runner, "_run_step", return_value={"name": "x", "success": True, "output": "", "duration_ms": 0}), \
             patch("agents.deploy.pipeline_runner._enqueue_dev_notification"), \
             patch.object(runner, "_post_pr_status"):
            runner.run(repo="vance-app", pr_number=42, branch="feat/x")

        mock_db.save_pipeline_run.assert_called_once()
        mock_db.update_pipeline_run.assert_called_once()

    def test_run_stops_on_first_failed_step(self, mock_db, cfg):
        runner = CIPipelineRunner(mock_db, cfg)
        steps_run = []

        def fake_step(name, *args, **kwargs):
            steps_run.append(name)
            return {"name": name, "success": name != "unit_tests", "output": "", "duration_ms": 0}

        with patch.object(runner, "_run_step", side_effect=fake_step), \
             patch("agents.deploy.pipeline_runner._enqueue_dev_notification"), \
             patch.object(runner, "_post_pr_status"):
            result = runner.run(repo="vance-app", pr_number=42, branch="feat/x")

        assert result["failed_step"] == "unit_tests"
        assert "integration_tests" not in steps_run

    def test_run_reports_success_true_when_all_steps_pass(self, mock_db, cfg):
        runner = CIPipelineRunner(mock_db, cfg)
        with patch.object(runner, "_run_step", return_value={"name": "x", "success": True, "output": "", "duration_ms": 0}), \
             patch("agents.deploy.pipeline_runner._enqueue_dev_notification"), \
             patch.object(runner, "_post_pr_status"):
            result = runner.run(repo="vance-app", pr_number=42, branch="feat/x")

        assert result["success"] is True
        assert result["failed_step"] is None

    def test_run_notifies_dev_agent(self, mock_db, cfg):
        runner = CIPipelineRunner(mock_db, cfg)
        with patch.object(runner, "_run_step", return_value={"name": "x", "success": True, "output": "", "duration_ms": 0}), \
             patch("agents.deploy.pipeline_runner._enqueue_dev_notification") as mock_notify, \
             patch.object(runner, "_post_pr_status"):
            runner.run(repo="vance-app", pr_number=42, branch="feat/x")

        mock_notify.assert_called_once()
        call_args = mock_notify.call_args[1] if mock_notify.call_args[1] else mock_notify.call_args[0]

    def test_step_cmd_node_lint(self, mock_db, cfg):
        runner = CIPipelineRunner(mock_db, cfg)
        cmd = runner._step_cmd("lint", "node")
        assert cmd == ["npm", "run", "lint"]

    def test_step_cmd_python_unit_tests(self, mock_db, cfg):
        runner = CIPipelineRunner(mock_db, cfg)
        cmd = runner._step_cmd("unit_tests", "python")
        assert "pytest" in cmd

    def test_run_step_returns_failure_on_subprocess_timeout(self, mock_db, cfg):
        runner = CIPipelineRunner(mock_db, cfg)
        import subprocess as sp
        with patch("agents.deploy.pipeline_runner.subprocess.run", side_effect=sp.TimeoutExpired("pytest", 300)):
            result = runner._run_step("unit_tests", "vance-app", "/tmp/repos/vance-app", {"type": "python"}, "main")

        assert result["success"] is False
        assert "timed out" in result["output"]

    def test_post_pr_status_skipped_when_no_github_token(self, cfg):
        db = MagicMock(spec=DeployDB)
        runner = CIPipelineRunner(db, {**cfg, "github_token": ""})
        # Should complete without error even without a token
        runner._post_pr_status("vance-app", 42, True, None, [])


# ---------------------------------------------------------------------------
# TestPromoter
# ---------------------------------------------------------------------------

class TestPromoter:

    def test_promote_blocked_when_ci_not_passed(self, mock_db, cfg):
        mock_db.get_latest_pipeline_run.return_value = _pipeline_run({"status": "failed"})
        promoter = Promoter(mock_db, cfg)
        result = promoter.promote(repo="vance-app", build_id="build_xyz")

        assert result["success"] is False
        assert result["blocked"] is True
        assert "CI" in result["reason"]

    def test_promote_blocked_when_no_pipeline_run(self, mock_db, cfg):
        mock_db.get_latest_pipeline_run.return_value = None
        promoter = Promoter(mock_db, cfg)
        result = promoter.promote(repo="vance-app", build_id="build_xyz")

        assert result["blocked"] is True

    def test_promote_blocked_during_blackout_window(self, mock_db, cfg):
        mock_db.get_latest_pipeline_run.return_value = _pipeline_run({"status": "success", "build_id": "build_xyz"})
        promoter = Promoter(mock_db, {**cfg, "blackout_windows": [{"days": list(range(7)), "start_hour": 0, "end_hour": 24}]})
        with patch.object(promoter, "_no_critical_bugs", return_value=True):
            result = promoter.promote(repo="vance-app", build_id="build_xyz")

        assert result["blocked"] is True
        assert "blackout" in result["reason"]

    def test_promote_blocked_when_critical_bugs_open(self, mock_db, cfg):
        mock_db.get_latest_pipeline_run.return_value = _pipeline_run({"status": "success", "build_id": "build_xyz"})
        promoter = Promoter(mock_db, cfg)
        with patch.object(promoter, "_no_critical_bugs", return_value=False), \
             patch.object(promoter, "_in_blackout_window", return_value=False):
            result = promoter.promote(repo="vance-app", build_id="build_xyz")

        assert result["blocked"] is True
        assert "P0" in result["reason"] or "bug" in result["reason"].lower()

    def test_promote_succeeds_when_all_checks_pass(self, mock_db, cfg):
        mock_db.get_latest_pipeline_run.return_value = _pipeline_run({"status": "success", "build_id": "build_xyz"})
        promoter = Promoter(mock_db, cfg)
        vercel_resp = {"uid": "dpl_123", "url": "vance.vercel.app", "readyState": "READY"}
        with patch.object(promoter, "_no_critical_bugs", return_value=True), \
             patch.object(promoter, "_in_blackout_window", return_value=False), \
             patch.object(promoter, "_deploy_vercel", return_value={"success": True, "vercel_deployment_id": "dpl_123", "url": "https://vance.so", "state": "READY"}), \
             patch("agents.deploy.promoter._enqueue_qa_regression"), \
             patch("agents.deploy.promoter._enqueue_release_notes"):
            result = promoter.promote(repo="vance-app", build_id="build_xyz")

        assert result["success"] is True
        mock_db.save_deployment.assert_called_once()
        mock_db.update_deployment.assert_called_once()

    def test_promote_saves_deployment_record(self, mock_db, cfg):
        mock_db.get_latest_pipeline_run.return_value = _pipeline_run({"status": "success", "build_id": "b1"})
        promoter = Promoter(mock_db, cfg)
        with patch.object(promoter, "_no_critical_bugs", return_value=True), \
             patch.object(promoter, "_in_blackout_window", return_value=False), \
             patch.object(promoter, "_deploy_vercel", return_value={"success": True, "url": "", "state": "READY", "vercel_deployment_id": "dpl_x"}), \
             patch("agents.deploy.promoter._enqueue_qa_regression"), \
             patch("agents.deploy.promoter._enqueue_release_notes"):
            promoter.promote(repo="vance-app", build_id="b1")

        mock_db.save_deployment.assert_called_once()
        call_kwargs = mock_db.save_deployment.call_args[1]
        assert call_kwargs["repo"] == "vance-app"
        assert call_kwargs["environment"] == "production"

    def test_promote_enqueues_qa_regression_on_success(self, mock_db, cfg):
        mock_db.get_latest_pipeline_run.return_value = _pipeline_run({"status": "success", "build_id": "b1"})
        promoter = Promoter(mock_db, cfg)
        with patch.object(promoter, "_no_critical_bugs", return_value=True), \
             patch.object(promoter, "_in_blackout_window", return_value=False), \
             patch.object(promoter, "_deploy_vercel", return_value={"success": True, "url": "", "state": "READY", "vercel_deployment_id": "dpl_x"}), \
             patch("agents.deploy.promoter._enqueue_qa_regression") as mock_qa, \
             patch("agents.deploy.promoter._enqueue_release_notes"):
            promoter.promote(repo="vance-app", build_id="b1")

        mock_qa.assert_called_once()

    def test_in_blackout_window_false_when_no_windows_configured(self, mock_db, cfg):
        promoter = Promoter(mock_db, {**cfg, "blackout_windows": []})
        assert promoter._in_blackout_window() is False

    def test_all_ci_passed_false_when_build_id_mismatch(self, mock_db, cfg):
        mock_db.get_latest_pipeline_run.return_value = _pipeline_run({"status": "success", "build_id": "other_build"})
        promoter = Promoter(mock_db, cfg)
        assert promoter._all_ci_passed("vance-app", "target_build") is False


# ---------------------------------------------------------------------------
# TestRollbackHandler
# ---------------------------------------------------------------------------

class TestRollbackHandler:

    def test_rollback_fails_when_no_previous_deployment(self, mock_db, cfg):
        mock_db.get_previous_deployment.return_value = None
        handler = RollbackHandler(mock_db, cfg)
        result = handler.rollback(repo="vance-app")

        assert result["success"] is False
        assert "no previous" in result["reason"].lower()

    def test_rollback_executes_vercel_rollback(self, mock_db, cfg):
        handler = RollbackHandler(mock_db, cfg)
        with patch.object(handler, "_execute_rollback", return_value=True) as mock_exec, \
             patch("agents.deploy.rollback_handler._notify_all_agents"):
            handler.rollback(repo="vance-app")

        mock_exec.assert_called_once_with("vance-app", "production", "prev_version_xyz")

    def test_rollback_notifies_all_agents_on_success(self, mock_db, cfg):
        handler = RollbackHandler(mock_db, cfg)
        with patch.object(handler, "_execute_rollback", return_value=True), \
             patch("agents.deploy.rollback_handler._notify_all_agents") as mock_notify:
            handler.rollback(repo="vance-app", reason="qa_regression")

        mock_notify.assert_called_once()
        _, kwargs = mock_notify.call_args[0], mock_notify.call_args[1] if mock_notify.call_args[1] else {}

    def test_rollback_notifies_support_when_many_users_affected(self, mock_db, cfg):
        handler = RollbackHandler(mock_db, cfg)
        with patch.object(handler, "_execute_rollback", return_value=True), \
             patch("agents.deploy.rollback_handler._notify_all_agents"), \
             patch("agents.deploy.rollback_handler._enqueue_support_message") as mock_support:
            handler.rollback(repo="vance-app", affected_users=200)

        mock_support.assert_called_once()

    def test_rollback_does_not_notify_support_under_threshold(self, mock_db, cfg):
        handler = RollbackHandler(mock_db, cfg)
        with patch.object(handler, "_execute_rollback", return_value=True), \
             patch("agents.deploy.rollback_handler._notify_all_agents"), \
             patch("agents.deploy.rollback_handler._enqueue_support_message") as mock_support:
            handler.rollback(repo="vance-app", affected_users=50)

        mock_support.assert_not_called()

    def test_rollback_returns_rolled_back_to_version(self, mock_db, cfg):
        handler = RollbackHandler(mock_db, cfg)
        with patch.object(handler, "_execute_rollback", return_value=True), \
             patch("agents.deploy.rollback_handler._notify_all_agents"):
            result = handler.rollback(repo="vance-app")

        assert result["rolled_back_to"] == "prev_version_xyz"
        assert result["success"] is True


# ---------------------------------------------------------------------------
# TestEnvSyncer
# ---------------------------------------------------------------------------

class TestEnvSyncer:

    def test_sync_returns_failure_without_staging_url(self, cfg):
        syncer = EnvSyncer({**cfg, "staging_db_url": ""})
        result = syncer.sync(repo="vance-app")
        assert result["success"] is False
        assert "staging_db_url" in result["reason"]

    def test_sync_schema_runs_pg_dump_and_psql(self, cfg):
        syncer = EnvSyncer(cfg)
        with patch("agents.deploy.env_syncer.subprocess.run") as mock_run:
            mock_run.return_value = _proc(returncode=0, stdout="-- schema")
            syncer._sync_schema()

        calls = mock_run.call_args_list
        cmds = [c[0][0] for c in calls]
        assert any("pg_dump" in cmd[0] for cmd in cmds)
        assert any("psql" in cmd[0] for cmd in cmds)

    def test_sync_schema_returns_false_on_pg_dump_failure(self, cfg):
        syncer = EnvSyncer(cfg)
        with patch("agents.deploy.env_syncer.subprocess.run", return_value=_proc(returncode=1, stderr="access denied")):
            result = syncer._sync_schema()
        assert result is False

    def test_sync_skips_seed_when_no_seed_cmd_configured(self, cfg):
        syncer = EnvSyncer({**cfg, "repos": {"vance-app": {**cfg["repos"]["vance-app"], "seed_cmd": ""}}})
        result = syncer._run_seed("vance-app")
        assert result is True

    def test_sync_returns_combined_success(self, cfg):
        syncer = EnvSyncer(cfg)
        with patch.object(syncer, "_sync_schema", return_value=True), \
             patch.object(syncer, "_run_seed", return_value=True):
            result = syncer.sync(repo="vance-app")

        assert result["success"] is True
        assert result["schema_synced"] is True
        assert result["seed_run"] is True

    def test_sync_reports_partial_failure(self, cfg):
        syncer = EnvSyncer(cfg)
        with patch.object(syncer, "_sync_schema", return_value=True), \
             patch.object(syncer, "_run_seed", return_value=False):
            result = syncer.sync(repo="vance-app")

        assert result["success"] is False
        assert result["schema_synced"] is True
        assert result["seed_run"] is False


# ---------------------------------------------------------------------------
# TestReleaseNotesGenerator
# ---------------------------------------------------------------------------

class TestReleaseNotesGenerator:

    def _prs(self, n: int = 3) -> list[dict]:
        return [
            {"number": i, "title": f"feat: thing {i}", "merged_at": "2026-06-12T00:00:00Z", "base": {"ref": "main"}}
            for i in range(1, n + 1)
        ]

    def test_generate_returns_empty_when_no_prs(self, mock_db, cfg):
        gen = ReleaseNotesGenerator(mock_db, cfg)
        with patch.object(gen, "_get_merged_prs", return_value=[]), \
             patch.object(gen, "_get_previous_tag", return_value=None):
            result = gen.generate(repo="vance-app", tag="v1.2.0")

        assert result["prs"] == 0
        assert result["notes"] == {}

    def test_generate_summarizes_prs_with_llm(self, mock_db, cfg):
        gen = ReleaseNotesGenerator(mock_db, cfg)
        llm_response = json.dumps({"new_features": ["New dashboard"], "bug_fixes": ["Fixed login"]})
        with patch.object(gen, "_get_merged_prs", return_value=self._prs(3)), \
             patch.object(gen, "_get_previous_tag", return_value="v1.1.0"), \
             patch.object(gen, "_summarize_with_llm", return_value={"new_features": ["New dashboard"]}), \
             patch.object(gen, "_post_github_release", return_value={"html_url": "https://github.com/..."}), \
             patch("agents.deploy.release_notes._enqueue_content_agent"):
            result = gen.generate(repo="vance-app", tag="v1.2.0")

        assert result["prs"] == 3
        assert "new_features" in result["notes"]

    def test_generate_posts_to_github_releases(self, mock_db, cfg):
        gen = ReleaseNotesGenerator(mock_db, cfg)
        with patch.object(gen, "_get_merged_prs", return_value=self._prs(2)), \
             patch.object(gen, "_get_previous_tag", return_value=None), \
             patch.object(gen, "_summarize_with_llm", return_value={"improvements": ["Better perf"]}), \
             patch.object(gen, "_post_github_release", return_value={"html_url": "https://github.com/r/1"}) as mock_release, \
             patch("agents.deploy.release_notes._enqueue_content_agent"):
            gen.generate(repo="vance-app", tag="v1.2.0")

        mock_release.assert_called_once()
        call_kwargs = mock_release.call_args
        assert "v1.2.0" in str(call_kwargs)

    def test_generate_enqueues_content_agent(self, mock_db, cfg):
        gen = ReleaseNotesGenerator(mock_db, cfg)
        with patch.object(gen, "_get_merged_prs", return_value=self._prs(2)), \
             patch.object(gen, "_get_previous_tag", return_value=None), \
             patch.object(gen, "_summarize_with_llm", return_value={"new_features": ["Thing"]}), \
             patch.object(gen, "_post_github_release", return_value={}), \
             patch("agents.deploy.release_notes._enqueue_content_agent") as mock_content:
            gen.generate(repo="vance-app", tag="v1.2.0")

        mock_content.assert_called_once()

    def test_summarize_with_llm_parses_json_response(self, mock_db, cfg):
        gen = ReleaseNotesGenerator(mock_db, cfg)
        notes = {"new_features": ["Feature A"], "bug_fixes": ["Fix B"]}
        with patch("agents.deploy.release_notes.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(notes))]
            result = gen._summarize_with_llm(self._prs(2))

        assert "new_features" in result
        assert result["new_features"] == ["Feature A"]

    def test_summarize_with_llm_falls_back_on_parse_error(self, mock_db, cfg):
        gen = ReleaseNotesGenerator(mock_db, cfg)
        with patch("agents.deploy.release_notes.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text="not valid json {{{")]
            result = gen._summarize_with_llm(self._prs(2))

        assert isinstance(result, dict)

    def test_format_markdown_contains_section_headers(self, mock_db, cfg):
        gen = ReleaseNotesGenerator(mock_db, cfg)
        notes = {"new_features": ["Feature A"], "bug_fixes": ["Fix B"]}
        md = gen._format_markdown("v1.2.0", notes)

        assert "New Features" in md or "new_features" in md.lower() or "✨" in md
        assert "Fix B" in md


# ---------------------------------------------------------------------------
# TestDeployAgent — full dispatch
# ---------------------------------------------------------------------------

class TestDeployAgent:

    def _make_agent(self):
        from agents.deploy.main import DeployAgent

        config = MagicMock(spec=AgentConfig)
        config.custom = _cfg()
        config.llm_system_prompt = None
        return DeployAgent("deploy", config)

    def test_unknown_action_returns_error(self):
        agent = self._make_agent()
        result = agent.handle(_task("not_a_real_action"))
        assert result.success is False
        assert "error" in result.output

    def test_ci_pipeline_requires_repo(self):
        agent = self._make_agent()
        result = agent.handle(_task("ci_pipeline"))
        assert result.output.get("error") is not None

    def test_ci_pipeline_dispatches(self):
        agent = self._make_agent()
        with patch.object(agent._pipeline, "run", return_value={"run_id": "x", "success": True, "steps": [], "failed_step": None, "duration_ms": 1000}) as m:
            result = agent.handle(_task("ci_pipeline", {"repo": "vance-app", "pr_number": 42, "branch": "feat/x"}))
        m.assert_called_once()
        assert result.success is True

    def test_promote_requires_repo_and_build_id(self):
        agent = self._make_agent()
        result = agent.handle(_task("promote_to_production", {"repo": "vance-app"}))
        assert "error" in result.output

    def test_promote_to_production_dispatches(self):
        agent = self._make_agent()
        with patch.object(agent._promoter, "promote", return_value={"success": True, "blocked": False}) as m:
            result = agent.handle(_task("promote_to_production", {"repo": "vance-app", "build_id": "b1"}))
        m.assert_called_once()
        assert result.success is True

    def test_rollback_requires_repo(self):
        agent = self._make_agent()
        result = agent.handle(_task("rollback"))
        assert "error" in result.output

    def test_rollback_dispatches(self):
        agent = self._make_agent()
        with patch.object(agent._rollback, "rollback", return_value={"success": True, "rolled_back_to": "v1"}) as m:
            result = agent.handle(_task("rollback", {"repo": "vance-app"}))
        m.assert_called_once()
        assert result.success is True

    def test_environment_sync_dispatches(self):
        agent = self._make_agent()
        with patch.object(agent._env_syncer, "sync", return_value={"success": True, "schema_synced": True, "seed_run": True}) as m:
            result = agent.handle(_task("environment_sync", {"repo": "vance-app"}))
        m.assert_called_once()
        assert result.success is True

    def test_environment_sync_requires_repo(self):
        agent = self._make_agent()
        result = agent.handle(_task("environment_sync"))
        assert "error" in result.output

    def test_release_notes_dispatches(self):
        agent = self._make_agent()
        with patch.object(agent._release_notes, "generate", return_value={"repo": "vance-app", "tag": "v1.0.0", "prs": 5, "notes": {}}) as m:
            result = agent.handle(_task("release_notes", {"repo": "vance-app", "tag": "v1.0.0"}))
        m.assert_called_once()
        assert result.success is True

    def test_release_notes_requires_repo_and_tag(self):
        agent = self._make_agent()
        result = agent.handle(_task("release_notes", {"repo": "vance-app"}))
        assert "error" in result.output

    def test_health_check_true_when_db_ok(self):
        agent = self._make_agent()
        with patch.object(agent._db, "get_latest_pipeline_run", return_value=None):
            assert agent.health_check() is True

    def test_health_check_false_on_db_error(self):
        agent = self._make_agent()
        with patch.object(agent._db, "get_latest_pipeline_run", side_effect=Exception("db down")):
            assert agent.health_check() is False
