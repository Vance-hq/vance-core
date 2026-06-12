"""Dev agent unit tests — no external services, no live subprocesses."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from subprocess import CompletedProcess
from unittest.mock import MagicMock, call, patch

import pytest

from agents._base import AgentConfig
from agents.dev.db import DevDB
from agents.dev.builder import Builder
from agents.dev.test_runner import TestRunner
from agents.dev.deployer import Deployer
from agents.dev.dep_updater import DependencyUpdater
from shared.types import AgentCapability, Task, TaskResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> CompletedProcess:
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


def _build_log(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "repo": "vance-app",
        "task_type": "build_feature",
        "issue_number": None,
        "success": True,
        "duration_seconds": 42,
        "error_msg": None,
    }
    if overrides:
        base.update(overrides)
    return base


@pytest.fixture
def mock_db():
    db = MagicMock(spec=DevDB)
    db.save_deployment.return_value = str(uuid.uuid4())
    db.save_build_log.return_value = str(uuid.uuid4())
    db.get_recent_deployments.return_value = [_deployment()]
    db.get_last_deployment.return_value = _deployment()
    return db


@pytest.fixture
def cfg() -> dict:
    return {
        "repos_path": "/tmp/repos",
        "github_token": "ghp_test",
        "github_org": "vance-hq",
        "vercel_token": "vercel_test",
        "vercel_team_id": "team_abc",
        "claude_code_bin": "/usr/local/bin/claude",
        "subprocess_timeout_s": 300,
        "deploy_poll_interval_s": 0,
        "repos": {
            "vance-app": {
                "type": "node",
                "vercel_project_id": "prj_vance_app",
                "default_branch": "main",
            },
            "vance-core": {
                "type": "python",
                "vercel_project_id": "",
                "default_branch": "main",
            },
        },
    }


# ---------------------------------------------------------------------------
# DevDB
# ---------------------------------------------------------------------------

class TestDevDB:

    def test_save_deployment_returns_id(self):
        db = DevDB.__new__(DevDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        expected = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected}

        with patch("agents.dev.db.get_db", return_value=mock_conn):
            result = db.save_deployment(
                repo="vance-app",
                environment="production",
                version="abc1234",
                status="pending",
                deployed_by_task_id="task_1",
            )
        assert result == expected

    def test_update_deployment_executes(self):
        db = DevDB.__new__(DevDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur

        with patch("agents.dev.db.get_db", return_value=mock_conn):
            db.update_deployment(deployment_id="dep_1", status="success")
        mock_cur.execute.assert_called_once()

    def test_save_build_log_returns_id(self):
        db = DevDB.__new__(DevDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        expected = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected}

        with patch("agents.dev.db.get_db", return_value=mock_conn):
            result = db.save_build_log(
                repo="vance-app",
                task_type="build_feature",
                success=True,
                duration_seconds=42,
            )
        assert result == expected

    def test_get_recent_deployments_returns_list(self):
        db = DevDB.__new__(DevDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchall.return_value = [_deployment(), _deployment()]

        with patch("agents.dev.db.get_db", return_value=mock_conn):
            results = db.get_recent_deployments(repo="vance-app", limit=5)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Builder — build_feature
# ---------------------------------------------------------------------------

class TestBuilderBuildFeature:

    def test_build_spawns_claude_code(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.Builder._open_pr") as mock_pr:
            mock_run.side_effect = [
                _proc(0),                          # git pull
                _proc(0),                          # git checkout -b
                _proc(0, stdout='{"result":"ok"}'), # claude
                _proc(0, stdout="1 passed"),       # tests
                _proc(0),                          # git add
                _proc(0),                          # git commit
                _proc(0),                          # git push
            ]
            mock_pr.return_value = {"number": 10, "html_url": "https://github.com/test/pr/10"}
            result = builder.build_feature(
                repo="vance-app",
                feature_description="Add dark mode toggle",
                acceptance_criteria="Toggle switches theme",
                target_branch="feature/dark-mode",
            )
        assert result["success"] is True
        claude_call = [c for c in mock_run.call_args_list if "claude" in str(c)]
        assert len(claude_call) >= 1

    def test_build_passes_structured_prompt_to_claude(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.Builder._open_pr"):
            mock_run.side_effect = [
                _proc(0), _proc(0),
                _proc(0, stdout='{"result":"ok"}'),
                _proc(0, stdout="1 passed"),
                _proc(0), _proc(0), _proc(0),
            ]
            builder.build_feature(
                repo="vance-app",
                feature_description="Add dark mode",
                acceptance_criteria="Toggle switches theme",
                target_branch="feature/dark-mode",
            )
        claude_call = next(c for c in mock_run.call_args_list if "claude" in str(c))
        assert "dark mode" in str(claude_call).lower()

    def test_build_opens_pr_on_test_pass(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.Builder._open_pr") as mock_pr:
            mock_run.side_effect = [
                _proc(0), _proc(0),
                _proc(0, stdout='{"result":"ok"}'),
                _proc(0, stdout="3 passed"),
                _proc(0), _proc(0), _proc(0),
            ]
            mock_pr.return_value = {"number": 5, "html_url": "https://github.com/test/pr/5"}
            result = builder.build_feature(
                repo="vance-app",
                feature_description="Feature X",
                acceptance_criteria="X works",
                target_branch="feature/x",
            )
        mock_pr.assert_called_once()
        assert result["pr_number"] == 5

    def test_build_retries_once_on_test_failure(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.Builder._open_pr") as mock_pr:
            mock_run.side_effect = [
                _proc(0), _proc(0),              # git pull, checkout
                _proc(0, stdout='{}'),           # claude attempt 1
                _proc(1, stderr="1 failed"),     # tests fail
                _proc(0, stdout='{}'),           # claude attempt 2 (retry)
                _proc(0, stdout="1 passed"),     # tests pass on retry
                _proc(0), _proc(0), _proc(0),   # git add, commit, push
            ]
            mock_pr.return_value = {"number": 7, "html_url": "https://github.com/test/pr/7"}
            result = builder.build_feature(
                repo="vance-app",
                feature_description="Feature Y",
                acceptance_criteria="Y works",
                target_branch="feature/y",
            )
        claude_calls = [c for c in mock_run.call_args_list if "claude" in str(c)]
        assert len(claude_calls) == 2
        assert result["success"] is True

    def test_build_flags_for_human_after_two_failures(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.Builder._open_pr"), \
             patch("agents.dev.builder.enqueue_human_review") as mock_flag:
            mock_run.side_effect = [
                _proc(0), _proc(0),
                _proc(0, stdout='{}'),
                _proc(1, stderr="2 failed"),
                _proc(0, stdout='{}'),
                _proc(1, stderr="2 failed"),
            ]
            result = builder.build_feature(
                repo="vance-app",
                feature_description="Feature Z",
                acceptance_criteria="Z works",
                target_branch="feature/z",
            )
        mock_flag.assert_called_once()
        assert result["success"] is False
        assert result.get("flagged_for_review") is True

    def test_build_logs_to_db(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.Builder._open_pr") as mock_pr:
            mock_run.side_effect = [
                _proc(0), _proc(0),
                _proc(0, stdout='{}'),
                _proc(0, stdout="1 passed"),
                _proc(0), _proc(0), _proc(0),
            ]
            mock_pr.return_value = {"number": 1, "html_url": "https://github.com/test/pr/1"}
            builder.build_feature(
                repo="vance-app",
                feature_description="Feature",
                acceptance_criteria="Works",
                target_branch="feature/test",
            )
        mock_db.save_build_log.assert_called_once()


# ---------------------------------------------------------------------------
# Builder — fix_bug
# ---------------------------------------------------------------------------

class TestBuilderFixBug:

    def test_fix_bug_fetches_github_issue(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.httpx") as mock_httpx, \
             patch("agents.dev.builder.Builder._open_pr") as mock_pr:
            issue_resp = MagicMock()
            issue_resp.status_code = 200
            issue_resp.json.return_value = {
                "number": 42, "title": "Login 500 error", "body": "Users get 500 on login"
            }
            mock_httpx.get.return_value = issue_resp
            mock_run.side_effect = [
                _proc(0), _proc(0),
                _proc(0, stdout='{}'),
                _proc(0, stdout="5 passed"),
                _proc(0), _proc(0), _proc(0),
            ]
            mock_pr.return_value = {"number": 43, "html_url": "https://github.com/test/pr/43"}
            result = builder.fix_bug(
                repo="vance-app",
                issue_number=42,
                issue_body="",
                error_logs="",
            )
        mock_httpx.get.assert_called_once()
        assert result["success"] is True

    def test_fix_bug_includes_error_logs_in_prompt(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.httpx") as mock_httpx, \
             patch("agents.dev.builder.Builder._open_pr") as mock_pr:
            issue_resp = MagicMock()
            issue_resp.status_code = 200
            issue_resp.json.return_value = {"number": 99, "title": "Bug", "body": "It broke"}
            mock_httpx.get.return_value = issue_resp
            mock_run.side_effect = [
                _proc(0), _proc(0),
                _proc(0, stdout='{}'),
                _proc(0, stdout="1 passed"),
                _proc(0), _proc(0), _proc(0),
            ]
            mock_pr.return_value = {"number": 100, "html_url": "https://github.com/test/pr/100"}
            builder.fix_bug(
                repo="vance-app",
                issue_number=99,
                issue_body="It broke",
                error_logs="TypeError at line 42",
            )
        claude_call = next(c for c in mock_run.call_args_list if "claude" in str(c))
        assert "TypeError" in str(claude_call)

    def test_fix_bug_closes_issue_on_pr_success(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.httpx") as mock_httpx, \
             patch("agents.dev.builder.Builder._open_pr") as mock_pr:
            issue_resp = MagicMock()
            issue_resp.status_code = 200
            issue_resp.json.return_value = {"number": 55, "title": "Bug", "body": "broken"}
            close_resp = MagicMock()
            close_resp.status_code = 200
            close_resp.json.return_value = {"state": "closed"}
            mock_httpx.get.return_value = issue_resp
            mock_httpx.patch.return_value = close_resp
            mock_run.side_effect = [
                _proc(0), _proc(0),
                _proc(0, stdout='{}'),
                _proc(0, stdout="1 passed"),
                _proc(0), _proc(0), _proc(0),
            ]
            mock_pr.return_value = {"number": 56, "html_url": "https://github.com/test/pr/56"}
            result = builder.fix_bug(
                repo="vance-app",
                issue_number=55,
                issue_body="broken",
                error_logs="",
            )
        mock_httpx.patch.assert_called_once()
        assert result["issue_closed"] is True


# ---------------------------------------------------------------------------
# Builder — hotfix
# ---------------------------------------------------------------------------

class TestBuilderHotfix:

    def test_hotfix_commits_directly_to_main(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.httpx") as mock_httpx, \
             patch("agents.dev.builder.enqueue_deploy") as mock_deploy:
            postmortem_resp = MagicMock()
            postmortem_resp.status_code = 201
            postmortem_resp.json.return_value = {"number": 77, "html_url": "https://github.com/test/issues/77"}
            mock_httpx.post.return_value = postmortem_resp
            mock_run.side_effect = [
                _proc(0),
                _proc(0, stdout='{}'),
                _proc(0, stdout="1 passed"),
                _proc(0), _proc(0), _proc(0),
            ]
            result = builder.hotfix(
                repo="vance-app",
                description="Fix null pointer in payment flow",
                error_context="NullPointerException at payments.py:42",
            )
        push_call = next(c for c in mock_run.call_args_list if "push" in str(c))
        assert "main" in str(push_call) or result.get("branch") == "main"
        assert result["success"] is True

    def test_hotfix_skips_pr_process(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.httpx") as mock_httpx, \
             patch("agents.dev.builder.enqueue_deploy"), \
             patch("agents.dev.builder.Builder._open_pr") as mock_pr:
            postmortem_resp = MagicMock()
            postmortem_resp.status_code = 201
            postmortem_resp.json.return_value = {"number": 78, "html_url": "..."}
            mock_httpx.post.return_value = postmortem_resp
            mock_run.side_effect = [
                _proc(0), _proc(0, stdout='{}'), _proc(0, stdout="1 passed"),
                _proc(0), _proc(0), _proc(0),
            ]
            builder.hotfix(repo="vance-app", description="Emergency fix", error_context="")
        mock_pr.assert_not_called()

    def test_hotfix_triggers_deploy(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.httpx") as mock_httpx, \
             patch("agents.dev.builder.enqueue_deploy") as mock_deploy:
            postmortem_resp = MagicMock()
            postmortem_resp.status_code = 201
            postmortem_resp.json.return_value = {"number": 79, "html_url": "..."}
            mock_httpx.post.return_value = postmortem_resp
            mock_run.side_effect = [
                _proc(0), _proc(0, stdout='{}'), _proc(0, stdout="1 passed"),
                _proc(0), _proc(0), _proc(0),
            ]
            builder.hotfix(repo="vance-app", description="Emergency fix", error_context="")
        mock_deploy.assert_called_once()

    def test_hotfix_creates_postmortem_issue(self, mock_db, cfg):
        builder = Builder(mock_db, cfg)
        with patch("agents.dev.builder.subprocess.run") as mock_run, \
             patch("agents.dev.builder.httpx") as mock_httpx, \
             patch("agents.dev.builder.enqueue_deploy"):
            postmortem_resp = MagicMock()
            postmortem_resp.status_code = 201
            postmortem_resp.json.return_value = {"number": 80, "html_url": "https://github.com/test/issues/80"}
            mock_httpx.post.return_value = postmortem_resp
            mock_run.side_effect = [
                _proc(0), _proc(0, stdout='{}'), _proc(0, stdout="1 passed"),
                _proc(0), _proc(0), _proc(0),
            ]
            result = builder.hotfix(
                repo="vance-app",
                description="Emergency fix",
                error_context="",
            )
        mock_httpx.post.assert_called_once()
        assert result["postmortem_issue"] == 80


# ---------------------------------------------------------------------------
# TestRunner
# ---------------------------------------------------------------------------

class TestTestRunner:

    def test_run_tests_calls_pytest_for_python(self, mock_db, cfg):
        runner = TestRunner(mock_db, cfg)
        with patch("agents.dev.test_runner.subprocess.run") as mock_run, \
             patch("agents.dev.test_runner.enqueue_fix_bug"):
            mock_run.return_value = _proc(0, stdout="5 passed, 0 failed")
            runner.run(repo="vance-core", test_type="unit")
        cmd_str = str(mock_run.call_args_list[0])
        assert "pytest" in cmd_str

    def test_run_tests_calls_npm_test_for_node(self, mock_db, cfg):
        runner = TestRunner(mock_db, cfg)
        with patch("agents.dev.test_runner.subprocess.run") as mock_run, \
             patch("agents.dev.test_runner.enqueue_fix_bug"):
            mock_run.return_value = _proc(0, stdout="Tests: 10 passed")
            runner.run(repo="vance-app", test_type="unit")
        cmd_str = str(mock_run.call_args_list[0])
        assert "npm" in cmd_str

    def test_run_tests_returns_pass_fail_counts(self, mock_db, cfg):
        runner = TestRunner(mock_db, cfg)
        with patch("agents.dev.test_runner.subprocess.run") as mock_run, \
             patch("agents.dev.test_runner.enqueue_fix_bug"):
            mock_run.return_value = _proc(0, stdout="7 passed, 2 failed")
            result = runner.run(repo="vance-core", test_type="unit")
        assert "passed" in result
        assert "failed" in result

    def test_run_tests_reports_success_on_zero_failures(self, mock_db, cfg):
        runner = TestRunner(mock_db, cfg)
        with patch("agents.dev.test_runner.subprocess.run") as mock_run, \
             patch("agents.dev.test_runner.enqueue_fix_bug"):
            mock_run.return_value = _proc(0, stdout="10 passed")
            result = runner.run(repo="vance-core", test_type="unit")
        assert result["success"] is True

    def test_run_tests_enqueues_fix_bug_on_failure(self, mock_db, cfg):
        runner = TestRunner(mock_db, cfg)
        with patch("agents.dev.test_runner.subprocess.run") as mock_run, \
             patch("agents.dev.test_runner.enqueue_fix_bug") as mock_enqueue:
            mock_run.return_value = _proc(1, stdout="3 passed, 2 failed",
                                          stderr="FAILED test_auth.py::test_login")
            runner.run(repo="vance-core", test_type="unit")
        mock_enqueue.assert_called_once()

    def test_run_tests_success_false_on_nonzero_exit(self, mock_db, cfg):
        runner = TestRunner(mock_db, cfg)
        with patch("agents.dev.test_runner.subprocess.run") as mock_run, \
             patch("agents.dev.test_runner.enqueue_fix_bug"):
            mock_run.return_value = _proc(1, stdout="3 passed, 2 failed")
            result = runner.run(repo="vance-core", test_type="unit")
        assert result["success"] is False

    def test_run_tests_logs_to_db(self, mock_db, cfg):
        runner = TestRunner(mock_db, cfg)
        with patch("agents.dev.test_runner.subprocess.run") as mock_run, \
             patch("agents.dev.test_runner.enqueue_fix_bug"):
            mock_run.return_value = _proc(0, stdout="5 passed")
            runner.run(repo="vance-core", test_type="unit")
        mock_db.save_build_log.assert_called_once()


# ---------------------------------------------------------------------------
# Deployer
# ---------------------------------------------------------------------------

class TestDeployer:

    def test_deploy_triggers_vercel(self, mock_db, cfg):
        deployer = Deployer(mock_db, cfg)
        with patch("agents.dev.deployer.VercelConnector") as MockVercel, \
             patch("agents.dev.deployer.notify_reporting"):
            vc = MockVercel.return_value
            vc.trigger_deploy.return_value = {"uid": "dep_abc", "url": "vance.vercel.app"}
            vc.get_deployment_status.return_value = {"readyState": "READY", "url": "vance.vercel.app"}
            result = deployer.deploy(repo="vance-app", environment="production")
        vc.trigger_deploy.assert_called_once()
        assert result["success"] is True

    def test_deploy_polls_for_status(self, mock_db, cfg):
        deployer = Deployer(mock_db, cfg)
        with patch("agents.dev.deployer.VercelConnector") as MockVercel, \
             patch("agents.dev.deployer.notify_reporting"):
            vc = MockVercel.return_value
            vc.trigger_deploy.return_value = {"uid": "dep_abc", "url": "vance.vercel.app"}
            vc.get_deployment_status.side_effect = [
                {"readyState": "BUILDING"},
                {"readyState": "READY", "url": "vance.vercel.app"},
            ]
            deployer.deploy(repo="vance-app", environment="production")
        assert vc.get_deployment_status.call_count == 2

    def test_deploy_saves_to_db(self, mock_db, cfg):
        deployer = Deployer(mock_db, cfg)
        with patch("agents.dev.deployer.VercelConnector") as MockVercel, \
             patch("agents.dev.deployer.notify_reporting"):
            vc = MockVercel.return_value
            vc.trigger_deploy.return_value = {"uid": "dep_abc", "url": "vance.vercel.app"}
            vc.get_deployment_status.return_value = {"readyState": "READY", "url": "vance.vercel.app"}
            deployer.deploy(repo="vance-app", environment="production")
        mock_db.save_deployment.assert_called()

    def test_deploy_notifies_reporting_on_success(self, mock_db, cfg):
        deployer = Deployer(mock_db, cfg)
        with patch("agents.dev.deployer.VercelConnector") as MockVercel, \
             patch("agents.dev.deployer.notify_reporting") as mock_notify:
            vc = MockVercel.return_value
            vc.trigger_deploy.return_value = {"uid": "dep_abc", "url": "vance.vercel.app"}
            vc.get_deployment_status.return_value = {"readyState": "READY", "url": "vance.vercel.app"}
            deployer.deploy(repo="vance-app", environment="production")
        mock_notify.assert_called_once()

    def test_deploy_triggers_rollback_on_failure(self, mock_db, cfg):
        deployer = Deployer(mock_db, cfg)
        with patch("agents.dev.deployer.VercelConnector") as MockVercel, \
             patch("agents.dev.deployer.notify_reporting"):
            vc = MockVercel.return_value
            vc.trigger_deploy.return_value = {"uid": "dep_bad", "url": "vance.vercel.app"}
            vc.get_deployment_status.return_value = {"readyState": "ERROR", "url": "vance.vercel.app"}
            result = deployer.deploy(repo="vance-app", environment="production")
        vc.rollback.assert_called_once()
        assert result["success"] is False

    def test_deploy_result_has_required_keys(self, mock_db, cfg):
        deployer = Deployer(mock_db, cfg)
        with patch("agents.dev.deployer.VercelConnector") as MockVercel, \
             patch("agents.dev.deployer.notify_reporting"):
            vc = MockVercel.return_value
            vc.trigger_deploy.return_value = {"uid": "dep_abc", "url": "vance.vercel.app"}
            vc.get_deployment_status.return_value = {"readyState": "READY", "url": "vance.vercel.app"}
            result = deployer.deploy(repo="vance-app", environment="production")
        for key in ("success", "repo", "environment", "deployment_id"):
            assert key in result


# ---------------------------------------------------------------------------
# DependencyUpdater
# ---------------------------------------------------------------------------

class TestDependencyUpdater:

    def test_update_runs_npm_outdated_for_node(self, mock_db, cfg):
        updater = DependencyUpdater(mock_db, cfg)
        with patch("agents.dev.dep_updater.subprocess.run") as mock_run, \
             patch("agents.dev.dep_updater.DependencyUpdater._open_pr"):
            mock_run.side_effect = [
                _proc(1, stdout=json.dumps({
                    "lodash": {"current": "4.17.20", "wanted": "4.17.21", "latest": "4.17.21"},
                })),
                _proc(0),
                _proc(0, stdout="5 passed"),
                _proc(0), _proc(0), _proc(0), _proc(0),  # checkout, add, commit, push
            ]
            updater.update(repo="vance-app")
        first_cmd = str(mock_run.call_args_list[0])
        assert "npm" in first_cmd and "outdated" in first_cmd

    def test_update_runs_pip_outdated_for_python(self, mock_db, cfg):
        updater = DependencyUpdater(mock_db, cfg)
        with patch("agents.dev.dep_updater.subprocess.run") as mock_run, \
             patch("agents.dev.dep_updater.DependencyUpdater._open_pr"):
            mock_run.side_effect = [
                _proc(0, stdout=json.dumps([
                    {"name": "requests", "version": "2.28.0", "latest_version": "2.31.0"},
                ])),
                _proc(0),
                _proc(0, stdout="10 passed"),
                _proc(0), _proc(0), _proc(0), _proc(0),  # checkout, add, commit, push
            ]
            updater.update(repo="vance-core")
        first_cmd = str(mock_run.call_args_list[0])
        assert "pip" in first_cmd

    def test_update_minor_patch_auto_applies(self, mock_db, cfg):
        updater = DependencyUpdater(mock_db, cfg)
        with patch("agents.dev.dep_updater.subprocess.run") as mock_run, \
             patch("agents.dev.dep_updater.DependencyUpdater._open_pr") as mock_pr:
            mock_run.side_effect = [
                _proc(1, stdout=json.dumps({
                    "axios": {"current": "1.3.0", "wanted": "1.3.4", "latest": "1.3.4"},
                })),
                _proc(0),
                _proc(0, stdout="5 passed"),
                _proc(0), _proc(0), _proc(0), _proc(0),  # checkout, add, commit, push
            ]
            mock_pr.return_value = {"number": 20, "html_url": "https://github.com/test/pr/20"}
            updater.update(repo="vance-app")
        install_calls = [c for c in mock_run.call_args_list if "install" in str(c)]
        assert len(install_calls) >= 1

    def test_update_major_version_not_auto_applied(self, mock_db, cfg):
        updater = DependencyUpdater(mock_db, cfg)
        with patch("agents.dev.dep_updater.subprocess.run") as mock_run, \
             patch("agents.dev.dep_updater.DependencyUpdater._open_pr"):
            mock_run.side_effect = [
                _proc(1, stdout=json.dumps({
                    "react": {"current": "17.0.2", "wanted": "17.0.2", "latest": "18.2.0"},
                })),
                _proc(0, stdout="5 passed"),
            ]
            result = updater.update(repo="vance-app")
        assert result.get("major_updates_pending", 0) >= 1

    def test_update_runs_tests_after_apply(self, mock_db, cfg):
        updater = DependencyUpdater(mock_db, cfg)
        with patch("agents.dev.dep_updater.subprocess.run") as mock_run, \
             patch("agents.dev.dep_updater.DependencyUpdater._open_pr"):
            mock_run.side_effect = [
                _proc(1, stdout=json.dumps({
                    "lodash": {"current": "4.17.20", "wanted": "4.17.21", "latest": "4.17.21"},
                })),
                _proc(0),
                _proc(0, stdout="5 passed"),
                _proc(0), _proc(0), _proc(0), _proc(0),  # checkout, add, commit, push
            ]
            updater.update(repo="vance-app")
        test_calls = [c for c in mock_run.call_args_list if "test" in str(c).lower()]
        assert len(test_calls) >= 1

    def test_update_result_has_metrics(self, mock_db, cfg):
        updater = DependencyUpdater(mock_db, cfg)
        with patch("agents.dev.dep_updater.subprocess.run") as mock_run, \
             patch("agents.dev.dep_updater.DependencyUpdater._open_pr"):
            mock_run.side_effect = [
                _proc(1, stdout=json.dumps({
                    "lodash": {"current": "4.17.20", "wanted": "4.17.21", "latest": "4.17.21"},
                })),
                _proc(0),
                _proc(0, stdout="5 passed"),
                _proc(0), _proc(0), _proc(0), _proc(0),  # checkout, add, commit, push
            ]
            result = updater.update(repo="vance-app")
        assert "updated" in result
        assert "major_updates_pending" in result


# ---------------------------------------------------------------------------
# DevAgent dispatch
# ---------------------------------------------------------------------------

class TestDevAgent:

    @pytest.fixture
    def agent(self, cfg):
        from agents.dev.main import DevAgent
        config = MagicMock(spec=AgentConfig)
        config.custom = cfg
        config.llm_system_prompt = ""
        config.poll_interval_seconds = 2
        with patch("agents.dev.main.DevDB"), \
             patch("agents.dev.main.Builder"), \
             patch("agents.dev.main.TestRunner"), \
             patch("agents.dev.main.Deployer"), \
             patch("agents.dev.main.DependencyUpdater"):
            return DevAgent("dev", config)

    def test_unknown_action_returns_error(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={"action": "hack_the_mainframe"},
        )
        result = agent.handle(task)
        assert result.success is False
        assert "error" in result.output

    def test_build_feature_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={
                "action": "build_feature",
                "repo": "vance-app",
                "feature_description": "Add dark mode",
                "acceptance_criteria": "Toggle works",
                "target_branch": "feature/dark-mode",
            },
        )
        agent._builder.build_feature.return_value = {"success": True, "pr_number": 10}
        result = agent.handle(task)
        assert result.success is True
        agent._builder.build_feature.assert_called_once()

    def test_fix_bug_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={
                "action": "fix_bug",
                "repo": "vance-app",
                "issue_number": 42,
                "issue_body": "500 error on login",
                "error_logs": "",
            },
        )
        agent._builder.fix_bug.return_value = {"success": True, "pr_number": 43}
        result = agent.handle(task)
        assert result.success is True
        agent._builder.fix_bug.assert_called_once()

    def test_run_tests_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={"action": "run_tests", "repo": "vance-core", "test_type": "unit"},
        )
        agent._test_runner.run.return_value = {"success": True, "passed": 5, "failed": 0}
        result = agent.handle(task)
        assert result.success is True
        agent._test_runner.run.assert_called_once()

    def test_deploy_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={"action": "deploy", "repo": "vance-app", "environment": "production"},
        )
        agent._deployer.deploy.return_value = {"success": True, "deployment_id": "dep_abc"}
        result = agent.handle(task)
        assert result.success is True
        agent._deployer.deploy.assert_called_once()

    def test_dependency_update_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={"action": "dependency_update", "repo": "vance-app"},
        )
        agent._dep_updater.update.return_value = {"updated": 3, "major_updates_pending": 1}
        result = agent.handle(task)
        assert result.success is True
        agent._dep_updater.update.assert_called_once()

    def test_hotfix_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={
                "action": "hotfix",
                "repo": "vance-app",
                "description": "Fix null pointer",
                "error_context": "NullPointer at line 42",
            },
        )
        agent._builder.hotfix.return_value = {"success": True, "postmortem_issue": 80}
        result = agent.handle(task)
        assert result.success is True
        agent._builder.hotfix.assert_called_once()

    def test_health_check_true_when_db_ok(self, agent):
        agent._db.get_recent_deployments.return_value = []
        assert agent.health_check() is True

    def test_health_check_false_on_db_error(self, agent):
        agent._db.get_recent_deployments.side_effect = Exception("db down")
        assert agent.health_check() is False
