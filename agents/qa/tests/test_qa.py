"""QA agent unit tests — no external services, no live subprocesses."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from agents._base import AgentConfig
from agents.qa.db import QaDB
from agents.qa.regression_runner import RegressionRunner
from agents.qa.test_writer import TestWriter
from agents.qa.bug_triager import BugTriager
from agents.qa.load_tester import LoadTester
from agents.qa.coverage_reporter import CoverageReporter
from shared.types import AgentCapability, Task, TaskResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> CompletedProcess:
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _test_run(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "repo": "vance-app",
        "run_type": "regression",
        "passed": 15,
        "failed": 0,
        "coverage_pct": 82.5,
        "duration_ms": 12000,
        "triggered_by": "deploy",
        "run_at": datetime.now(timezone.utc),
    }
    if overrides:
        base.update(overrides)
    return base


def _bug(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "product": "localoutrank",
        "severity": "P2",
        "title": "Dashboard charts not loading",
        "stack_trace": "TypeError: Cannot read property 'data' of undefined",
        "affected_users": 3,
        "status": "open",
        "created_at": datetime.now(timezone.utc),
        "resolved_at": None,
    }
    if overrides:
        base.update(overrides)
    return base


@pytest.fixture
def mock_db():
    db = MagicMock(spec=QaDB)
    db.save_test_run.return_value = str(uuid.uuid4())
    db.get_recent_runs.return_value = [_test_run()]
    db.save_bug.return_value = str(uuid.uuid4())
    db.get_open_bugs.return_value = [_bug()]
    db.update_bug.return_value = None
    return db


@pytest.fixture
def cfg() -> dict:
    return {
        "repos_path": "/tmp/repos",
        "github_token": "ghp_test",
        "github_org": "vance-hq",
        "subprocess_timeout_s": 60,
        "load_test_timeout_s": 120,
        "p99_alert_threshold_ms": 2000,
        "coverage_threshold_pct": 60.0,
        "repos": {
            "vance-app": {"type": "node", "default_branch": "main"},
            "vance-core": {"type": "python", "default_branch": "main"},
        },
        "products": {
            "starpio": {
                "repo": "vance-app",
                "playwright_tag": "@starpio",
                "critical_flows": ["signup", "connect_gbp", "receive_review", "ai_response"],
            },
            "oneserv": {
                "repo": "vance-app",
                "playwright_tag": "@oneserv",
                "critical_flows": ["signup", "create_job", "dispatch", "invoice"],
            },
            "localoutrank": {
                "repo": "vance-app",
                "playwright_tag": "@localoutrank",
                "critical_flows": ["signup", "run_audit", "view_report", "export"],
            },
            "trusted_plumbing": {
                "repo": "trusted-plumbing-site",
                "playwright_tag": "@trusted_plumbing",
                "critical_flows": ["contact_form", "confirmation_email"],
            },
        },
    }


# ---------------------------------------------------------------------------
# QaDB
# ---------------------------------------------------------------------------

class TestQaDB:

    def test_save_test_run_returns_id(self):
        db = QaDB.__new__(QaDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        expected = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected}

        with patch("agents.qa.db.get_db", return_value=mock_conn):
            result = db.save_test_run(
                repo="vance-app",
                run_type="regression",
                passed=10,
                failed=0,
                coverage_pct=85.0,
                duration_ms=5000,
                triggered_by="deploy",
            )
        assert result == expected

    def test_save_bug_returns_id(self):
        db = QaDB.__new__(QaDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        expected = str(uuid.uuid4())
        mock_cur.fetchone.return_value = {"id": expected}

        with patch("agents.qa.db.get_db", return_value=mock_conn):
            result = db.save_bug(
                product="localoutrank",
                severity="P2",
                title="Dashboard broken",
                stack_trace="TypeError",
                affected_users=5,
            )
        assert result == expected

    def test_update_bug_executes(self):
        db = QaDB.__new__(QaDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur

        with patch("agents.qa.db.get_db", return_value=mock_conn):
            db.update_bug(bug_id="bug_1", status="resolved")
        mock_cur.execute.assert_called_once()

    def test_get_recent_runs_returns_list(self):
        db = QaDB.__new__(QaDB)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchall.return_value = [_test_run(), _test_run()]

        with patch("agents.qa.db.get_db", return_value=mock_conn):
            results = db.get_recent_runs(repo="vance-app", limit=5)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# RegressionRunner
# ---------------------------------------------------------------------------

class TestRegressionRunner:

    def test_run_executes_playwright_for_product(self, mock_db, cfg):
        runner = RegressionRunner(mock_db, cfg)
        with patch("agents.qa.regression_runner.subprocess.run") as mock_run:
            mock_run.return_value = _proc(0, stdout=json.dumps({
                "stats": {"expected": 5, "passed": 5, "failed": 0, "flaky": 0},
                "suites": [],
            }))
            result = runner.run(product="localoutrank", triggered_by="deploy")
        cmd_str = str(mock_run.call_args_list[0])
        assert "playwright" in cmd_str.lower()

    def test_run_filters_by_product_tag(self, mock_db, cfg):
        runner = RegressionRunner(mock_db, cfg)
        with patch("agents.qa.regression_runner.subprocess.run") as mock_run:
            mock_run.return_value = _proc(0, stdout=json.dumps({
                "stats": {"expected": 4, "passed": 4, "failed": 0, "flaky": 0},
                "suites": [],
            }))
            runner.run(product="starpio", triggered_by="deploy")
        cmd_str = str(mock_run.call_args_list[0])
        assert "@starpio" in cmd_str

    def test_run_saves_to_db(self, mock_db, cfg):
        runner = RegressionRunner(mock_db, cfg)
        with patch("agents.qa.regression_runner.subprocess.run") as mock_run:
            mock_run.return_value = _proc(0, stdout=json.dumps({
                "stats": {"expected": 5, "passed": 5, "failed": 0, "flaky": 0},
                "suites": [],
            }))
            runner.run(product="localoutrank", triggered_by="deploy")
        mock_db.save_test_run.assert_called_once()

    def test_run_returns_pass_fail_counts(self, mock_db, cfg):
        runner = RegressionRunner(mock_db, cfg)
        with patch("agents.qa.regression_runner.subprocess.run") as mock_run:
            mock_run.return_value = _proc(0, stdout=json.dumps({
                "stats": {"expected": 5, "passed": 4, "failed": 1, "flaky": 0},
                "suites": [],
            }))
            result = runner.run(product="localoutrank", triggered_by="deploy")
        assert result["passed"] == 4
        assert result["failed"] == 1

    def test_failure_alerts_dev_and_reporting(self, mock_db, cfg):
        runner = RegressionRunner(mock_db, cfg)
        with patch("agents.qa.regression_runner.subprocess.run") as mock_run, \
             patch("agents.qa.regression_runner.enqueue_dev_alert") as mock_dev, \
             patch("agents.qa.regression_runner.enqueue_reporting_alert") as mock_rep:
            mock_run.return_value = _proc(1, stdout=json.dumps({
                "stats": {"expected": 5, "passed": 3, "failed": 2, "flaky": 0},
                "suites": [],
            }))
            result = runner.run(product="localoutrank", triggered_by="deploy")
        mock_dev.assert_called_once()
        mock_rep.assert_called_once()
        assert result["success"] is False

    def test_success_returns_true(self, mock_db, cfg):
        runner = RegressionRunner(mock_db, cfg)
        with patch("agents.qa.regression_runner.subprocess.run") as mock_run:
            mock_run.return_value = _proc(0, stdout=json.dumps({
                "stats": {"expected": 5, "passed": 5, "failed": 0, "flaky": 0},
                "suites": [],
            }))
            result = runner.run(product="localoutrank", triggered_by="deploy")
        assert result["success"] is True


# ---------------------------------------------------------------------------
# TestWriter
# ---------------------------------------------------------------------------

class TestTestWriter:

    def test_write_generates_unit_tests(self, mock_db, cfg):
        writer = TestWriter(mock_db, cfg)
        with patch("agents.qa.test_writer.llm") as mock_llm, \
             patch("agents.qa.test_writer.subprocess.run") as mock_run:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "unit_tests": "def test_feature():\n    assert True",
                    "integration_test": "def test_integration():\n    pass",
                    "e2e_test": "test('signup flow', async ({page}) => { });",
                }))
            ]
            mock_run.return_value = _proc(0)
            result = writer.write(
                repo="vance-core",
                feature_code="def add_keyword(user_id, keyword): pass",
                acceptance_criteria="User can add a keyword",
                branch="feature/add-keyword",
            )
        assert result["unit_tests_written"] is True

    def test_write_generates_e2e_test(self, mock_db, cfg):
        writer = TestWriter(mock_db, cfg)
        with patch("agents.qa.test_writer.llm") as mock_llm, \
             patch("agents.qa.test_writer.subprocess.run") as mock_run:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "unit_tests": "def test_x(): pass",
                    "integration_test": "def test_int(): pass",
                    "e2e_test": "test('add keyword e2e', async ({page}) => { await page.goto('/'); });",
                }))
            ]
            mock_run.return_value = _proc(0)
            result = writer.write(
                repo="vance-core",
                feature_code="def add_keyword(user_id, keyword): pass",
                acceptance_criteria="User can add a keyword",
                branch="feature/add-keyword",
            )
        assert result["e2e_test_written"] is True

    def test_write_commits_tests_to_branch(self, mock_db, cfg):
        writer = TestWriter(mock_db, cfg)
        with patch("agents.qa.test_writer.llm") as mock_llm, \
             patch("agents.qa.test_writer.subprocess.run") as mock_run:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "unit_tests": "def test_x(): pass",
                    "integration_test": "def test_int(): pass",
                    "e2e_test": "test('e2e', async ({page}) => {});",
                }))
            ]
            mock_run.return_value = _proc(0)
            writer.write(
                repo="vance-core",
                feature_code="def f(): pass",
                acceptance_criteria="f works",
                branch="feature/my-feature",
            )
        git_calls = [c for c in mock_run.call_args_list if "git" in str(c)]
        assert len(git_calls) >= 1

    def test_write_saves_run_to_db(self, mock_db, cfg):
        writer = TestWriter(mock_db, cfg)
        with patch("agents.qa.test_writer.llm") as mock_llm, \
             patch("agents.qa.test_writer.subprocess.run") as mock_run:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "unit_tests": "def test_x(): pass",
                    "integration_test": "def test_int(): pass",
                    "e2e_test": "test('e2e', async () => {});",
                }))
            ]
            mock_run.return_value = _proc(0)
            writer.write(
                repo="vance-core",
                feature_code="def f(): pass",
                acceptance_criteria="f works",
                branch="feature/my-feature",
            )
        mock_db.save_test_run.assert_called_once()

    def test_write_result_has_file_paths(self, mock_db, cfg):
        writer = TestWriter(mock_db, cfg)
        with patch("agents.qa.test_writer.llm") as mock_llm, \
             patch("agents.qa.test_writer.subprocess.run") as mock_run:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "unit_tests": "def test_x(): pass",
                    "integration_test": "def test_int(): pass",
                    "e2e_test": "test('e2e', async () => {});",
                }))
            ]
            mock_run.return_value = _proc(0)
            result = writer.write(
                repo="vance-core",
                feature_code="def f(): pass",
                acceptance_criteria="f works",
                branch="feature/my-feature",
            )
        assert "files_written" in result


# ---------------------------------------------------------------------------
# BugTriager
# ---------------------------------------------------------------------------

class TestBugTriager:

    def test_triage_classifies_severity(self, mock_db, cfg):
        triager = BugTriager(mock_db, cfg)
        with patch("agents.qa.bug_triager.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "severity": "P2",
                    "likely_cause": "Null pointer in dashboard component",
                    "affected_component": "frontend/dashboard",
                }))
            ]
            result = triager.triage(
                product="localoutrank",
                error_log="TypeError at dashboard.js:42",
                stack_trace="TypeError: Cannot read property 'data'",
                affected_users_count=3,
            )
        assert result["severity"] == "P2"

    def test_p0_enqueues_hotfix_immediately(self, mock_db, cfg):
        triager = BugTriager(mock_db, cfg)
        with patch("agents.qa.bug_triager.llm") as mock_llm, \
             patch("agents.qa.bug_triager.enqueue_hotfix") as mock_hotfix:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "severity": "P0",
                    "likely_cause": "Database connection dropped",
                    "affected_component": "backend/db",
                }))
            ]
            triager.triage(
                product="localoutrank",
                error_log="FATAL: database connection refused",
                stack_trace="ConnectionError: ECONNREFUSED",
                affected_users_count=500,
            )
        mock_hotfix.assert_called_once()

    def test_p1_enqueues_fix_bug(self, mock_db, cfg):
        triager = BugTriager(mock_db, cfg)
        with patch("agents.qa.bug_triager.llm") as mock_llm, \
             patch("agents.qa.bug_triager.enqueue_fix_bug") as mock_fix:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "severity": "P1",
                    "likely_cause": "API endpoint returning 500",
                    "affected_component": "backend/api/reviews",
                }))
            ]
            triager.triage(
                product="starpio",
                error_log="500 Internal Server Error on /api/reviews",
                stack_trace="Error: unhandled exception",
                affected_users_count=50,
            )
        mock_fix.assert_called_once()

    def test_p2_creates_github_issue(self, mock_db, cfg):
        triager = BugTriager(mock_db, cfg)
        with patch("agents.qa.bug_triager.llm") as mock_llm, \
             patch("agents.qa.bug_triager.httpx") as mock_httpx:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "severity": "P2",
                    "likely_cause": "Charts not rendering",
                    "affected_component": "frontend/charts",
                }))
            ]
            issue_resp = MagicMock()
            issue_resp.status_code = 201
            issue_resp.json.return_value = {"number": 99, "html_url": "https://github.com/test/issues/99"}
            mock_httpx.post.return_value = issue_resp
            result = triager.triage(
                product="localoutrank",
                error_log="Charts empty",
                stack_trace="",
                affected_users_count=5,
            )
        mock_httpx.post.assert_called_once()
        assert result["github_issue"] == 99

    def test_p3_creates_github_issue(self, mock_db, cfg):
        triager = BugTriager(mock_db, cfg)
        with patch("agents.qa.bug_triager.llm") as mock_llm, \
             patch("agents.qa.bug_triager.httpx") as mock_httpx:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "severity": "P3",
                    "likely_cause": "Minor UI misalignment",
                    "affected_component": "frontend/settings",
                }))
            ]
            issue_resp = MagicMock()
            issue_resp.status_code = 201
            issue_resp.json.return_value = {"number": 100, "html_url": "https://github.com/test/issues/100"}
            mock_httpx.post.return_value = issue_resp
            triager.triage(
                product="localoutrank",
                error_log="Button misaligned",
                stack_trace="",
                affected_users_count=1,
            )
        mock_httpx.post.assert_called_once()

    def test_triage_saves_bug_to_db(self, mock_db, cfg):
        triager = BugTriager(mock_db, cfg)
        with patch("agents.qa.bug_triager.llm") as mock_llm, \
             patch("agents.qa.bug_triager.httpx") as mock_httpx:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "severity": "P2",
                    "likely_cause": "UI bug",
                    "affected_component": "frontend",
                }))
            ]
            issue_resp = MagicMock()
            issue_resp.status_code = 201
            issue_resp.json.return_value = {"number": 101, "html_url": "..."}
            mock_httpx.post.return_value = issue_resp
            triager.triage(
                product="localoutrank",
                error_log="Error",
                stack_trace="",
                affected_users_count=2,
            )
        mock_db.save_bug.assert_called_once()

    def test_triage_result_has_required_keys(self, mock_db, cfg):
        triager = BugTriager(mock_db, cfg)
        with patch("agents.qa.bug_triager.llm") as mock_llm, \
             patch("agents.qa.bug_triager.httpx") as mock_httpx:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "severity": "P3",
                    "likely_cause": "Minor issue",
                    "affected_component": "frontend",
                }))
            ]
            issue_resp = MagicMock()
            issue_resp.status_code = 201
            issue_resp.json.return_value = {"number": 102, "html_url": "..."}
            mock_httpx.post.return_value = issue_resp
            result = triager.triage(
                product="localoutrank",
                error_log="minor issue",
                stack_trace="",
                affected_users_count=1,
            )
        for key in ("severity", "likely_cause", "affected_component", "bug_id"):
            assert key in result


# ---------------------------------------------------------------------------
# LoadTester
# ---------------------------------------------------------------------------

class TestLoadTester:

    def test_load_test_runs_locust(self, mock_db, cfg):
        tester = LoadTester(mock_db, cfg)
        locust_csv = (
            "Name,Request Count,Failure Count,Median Response Time,"
            "Average Response Time,Min Response Time,Max Response Time,"
            "Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,"
            "90%,95%,98%,99%,99.9%,99.99%,100%\n"
            "GET /api/data,1000,5,120,130,50,500,1024,33.3,0.2,"
            "120,130,150,160,200,250,400,500,800,900,1500\n"
        )
        with patch("agents.qa.load_tester.subprocess.run") as mock_run:
            mock_run.return_value = _proc(0, stdout=locust_csv)
            result = tester.run(
                endpoint="https://localoutrank.com/api/data",
                expected_rps=30,
                test_duration_seconds=10,
            )
        cmd_str = str(mock_run.call_args_list[0])
        assert "locust" in cmd_str.lower()

    def test_load_test_returns_latency_metrics(self, mock_db, cfg):
        tester = LoadTester(mock_db, cfg)
        locust_csv = (
            "Name,Request Count,Failure Count,Median Response Time,"
            "Average Response Time,Min Response Time,Max Response Time,"
            "Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,"
            "90%,95%,98%,99%,99.9%,99.99%,100%\n"
            "GET /api/data,1000,5,120,130,50,500,1024,33.3,0.2,"
            "120,130,150,160,200,250,400,500,800,900,1500\n"
        )
        with patch("agents.qa.load_tester.subprocess.run") as mock_run:
            mock_run.return_value = _proc(0, stdout=locust_csv)
            result = tester.run(
                endpoint="https://localoutrank.com/api/data",
                expected_rps=30,
                test_duration_seconds=10,
            )
        for key in ("p50_ms", "p95_ms", "p99_ms", "error_rate", "rps"):
            assert key in result

    def test_load_test_flags_slow_p99(self, mock_db, cfg):
        tester = LoadTester(mock_db, cfg)
        locust_csv = (
            "Name,Request Count,Failure Count,Median Response Time,"
            "Average Response Time,Min Response Time,Max Response Time,"
            "Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,"
            "90%,95%,98%,99%,99.9%,99.99%,100%\n"
            "GET /api/slow,500,2,300,350,100,5000,2048,16.7,0.1,"
            "300,400,500,600,800,1000,1500,2500,3000,4000,5000\n"
        )
        with patch("agents.qa.load_tester.subprocess.run") as mock_run, \
             patch("agents.qa.load_tester.enqueue_optimization") as mock_opt:
            mock_run.return_value = _proc(0, stdout=locust_csv)
            result = tester.run(
                endpoint="https://localoutrank.com/api/slow",
                expected_rps=15,
                test_duration_seconds=10,
            )
        mock_opt.assert_called_once()
        assert result["p99_exceeds_threshold"] is True

    def test_load_test_no_flag_when_p99_ok(self, mock_db, cfg):
        tester = LoadTester(mock_db, cfg)
        locust_csv = (
            "Name,Request Count,Failure Count,Median Response Time,"
            "Average Response Time,Min Response Time,Max Response Time,"
            "Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,"
            "90%,95%,98%,99%,99.9%,99.99%,100%\n"
            "GET /api/fast,1000,0,80,90,20,200,512,33.3,0.0,"
            "80,90,100,110,140,160,180,200,250,280,320\n"
        )
        with patch("agents.qa.load_tester.subprocess.run") as mock_run, \
             patch("agents.qa.load_tester.enqueue_optimization") as mock_opt:
            mock_run.return_value = _proc(0, stdout=locust_csv)
            result = tester.run(
                endpoint="https://localoutrank.com/api/fast",
                expected_rps=30,
                test_duration_seconds=10,
            )
        mock_opt.assert_not_called()
        assert result["p99_exceeds_threshold"] is False

    def test_load_test_saves_run_to_db(self, mock_db, cfg):
        tester = LoadTester(mock_db, cfg)
        locust_csv = (
            "Name,Request Count,Failure Count,Median Response Time,"
            "Average Response Time,Min Response Time,Max Response Time,"
            "Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,"
            "90%,95%,98%,99%,99.9%,99.99%,100%\n"
            "GET /api/data,100,0,100,110,50,200,512,10.0,0.0,"
            "100,110,120,130,150,160,170,180,190,195,200\n"
        )
        with patch("agents.qa.load_tester.subprocess.run") as mock_run:
            mock_run.return_value = _proc(0, stdout=locust_csv)
            tester.run(
                endpoint="https://localoutrank.com/api/data",
                expected_rps=10,
                test_duration_seconds=10,
            )
        mock_db.save_test_run.assert_called_once()


# ---------------------------------------------------------------------------
# CoverageReporter
# ---------------------------------------------------------------------------

class TestCoverageReporter:

    def test_report_runs_coverage_tool_for_python(self, mock_db, cfg):
        reporter = CoverageReporter(mock_db, cfg)
        cov_json = json.dumps({
            "totals": {"percent_covered": 78.5},
            "files": {
                "agents/foo.py": {"summary": {"percent_covered": 45.0}},
                "agents/bar.py": {"summary": {"percent_covered": 92.0}},
                "agents/baz.py": {"summary": {"percent_covered": 30.0}},
            },
        })
        with patch("agents.qa.coverage_reporter.subprocess.run") as mock_run, \
             patch("agents.qa.coverage_reporter.enqueue_write_tests"), \
             patch("agents.qa.coverage_reporter.notify_reporting"):
            mock_run.return_value = _proc(0, stdout=cov_json)
            result = reporter.report(repo="vance-core")
        cmd_str = str(mock_run.call_args_list[0])
        assert "pytest" in cmd_str or "coverage" in cmd_str

    def test_report_runs_coverage_for_node(self, mock_db, cfg):
        reporter = CoverageReporter(mock_db, cfg)
        cov_json = json.dumps({
            "total": {"lines": {"pct": 72.0}},
            "src/components/Foo.tsx": {"lines": {"pct": 40.0}},
            "src/components/Bar.tsx": {"lines": {"pct": 95.0}},
        })
        with patch("agents.qa.coverage_reporter.subprocess.run") as mock_run, \
             patch("agents.qa.coverage_reporter.enqueue_write_tests"), \
             patch("agents.qa.coverage_reporter.notify_reporting"):
            mock_run.return_value = _proc(0, stdout=cov_json)
            result = reporter.report(repo="vance-app")
        cmd_str = str(mock_run.call_args_list[0])
        assert "npm" in cmd_str or "jest" in cmd_str

    def test_report_identifies_low_coverage_files(self, mock_db, cfg):
        reporter = CoverageReporter(mock_db, cfg)
        cov_json = json.dumps({
            "totals": {"percent_covered": 78.5},
            "files": {
                "agents/low1.py": {"summary": {"percent_covered": 20.0}},
                "agents/low2.py": {"summary": {"percent_covered": 35.0}},
                "agents/low3.py": {"summary": {"percent_covered": 45.0}},
                "agents/high.py": {"summary": {"percent_covered": 90.0}},
            },
        })
        with patch("agents.qa.coverage_reporter.subprocess.run") as mock_run, \
             patch("agents.qa.coverage_reporter.enqueue_write_tests"), \
             patch("agents.qa.coverage_reporter.notify_reporting"):
            mock_run.return_value = _proc(0, stdout=cov_json)
            result = reporter.report(repo="vance-core")
        assert len(result["low_coverage_files"]) >= 3

    def test_report_enqueues_write_tests_for_worst_files(self, mock_db, cfg):
        reporter = CoverageReporter(mock_db, cfg)
        cov_json = json.dumps({
            "totals": {"percent_covered": 50.0},
            "files": {
                f"agents/file{i}.py": {"summary": {"percent_covered": float(10 + i * 5)}}
                for i in range(6)
            },
        })
        with patch("agents.qa.coverage_reporter.subprocess.run") as mock_run, \
             patch("agents.qa.coverage_reporter.enqueue_write_tests") as mock_enqueue, \
             patch("agents.qa.coverage_reporter.notify_reporting"):
            mock_run.return_value = _proc(0, stdout=cov_json)
            reporter.report(repo="vance-core")
        assert mock_enqueue.call_count == 3

    def test_report_notifies_reporting_agent(self, mock_db, cfg):
        reporter = CoverageReporter(mock_db, cfg)
        cov_json = json.dumps({
            "totals": {"percent_covered": 82.0},
            "files": {},
        })
        with patch("agents.qa.coverage_reporter.subprocess.run") as mock_run, \
             patch("agents.qa.coverage_reporter.enqueue_write_tests"), \
             patch("agents.qa.coverage_reporter.notify_reporting") as mock_notify:
            mock_run.return_value = _proc(0, stdout=cov_json)
            reporter.report(repo="vance-core")
        mock_notify.assert_called_once()

    def test_report_saves_to_db(self, mock_db, cfg):
        reporter = CoverageReporter(mock_db, cfg)
        cov_json = json.dumps({
            "totals": {"percent_covered": 82.0},
            "files": {},
        })
        with patch("agents.qa.coverage_reporter.subprocess.run") as mock_run, \
             patch("agents.qa.coverage_reporter.enqueue_write_tests"), \
             patch("agents.qa.coverage_reporter.notify_reporting"):
            mock_run.return_value = _proc(0, stdout=cov_json)
            reporter.report(repo="vance-core")
        mock_db.save_test_run.assert_called_once()


# ---------------------------------------------------------------------------
# QaAgent dispatch
# ---------------------------------------------------------------------------

class TestQaAgent:

    @pytest.fixture
    def agent(self, cfg):
        from agents.qa.main import QaAgent
        config = MagicMock(spec=AgentConfig)
        config.custom = cfg
        config.llm_system_prompt = ""
        config.poll_interval_seconds = 2
        with patch("agents.qa.main.QaDB"), \
             patch("agents.qa.main.RegressionRunner"), \
             patch("agents.qa.main.TestWriter"), \
             patch("agents.qa.main.BugTriager"), \
             patch("agents.qa.main.LoadTester"), \
             patch("agents.qa.main.CoverageReporter"):
            return QaAgent("qa", config)

    def test_unknown_action_returns_error(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={"action": "hack_tests"},
        )
        result = agent.handle(task)
        assert result.success is False
        assert "error" in result.output

    def test_run_regression_suite_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={"action": "run_regression_suite", "product": "localoutrank", "triggered_by": "deploy"},
        )
        agent._regression.run.return_value = {"success": True, "passed": 5, "failed": 0}
        result = agent.handle(task)
        assert result.success is True
        agent._regression.run.assert_called_once()

    def test_write_tests_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={
                "action": "write_tests",
                "repo": "vance-core",
                "feature_code": "def f(): pass",
                "acceptance_criteria": "f works",
                "branch": "feature/f",
            },
        )
        agent._writer.write.return_value = {"unit_tests_written": True, "e2e_test_written": True}
        result = agent.handle(task)
        assert result.success is True
        agent._writer.write.assert_called_once()

    def test_bug_triage_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={
                "action": "bug_triage",
                "product": "localoutrank",
                "error_log": "TypeError",
                "stack_trace": "Error at line 42",
                "affected_users_count": 5,
            },
        )
        agent._triager.triage.return_value = {"severity": "P2", "bug_id": "bug_1"}
        result = agent.handle(task)
        assert result.success is True
        agent._triager.triage.assert_called_once()

    def test_load_test_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={
                "action": "load_test",
                "endpoint": "https://localoutrank.com/api/data",
                "expected_rps": 30,
                "test_duration_seconds": 10,
            },
        )
        agent._load_tester.run.return_value = {"p99_ms": 450, "p99_exceeds_threshold": False}
        result = agent.handle(task)
        assert result.success is True
        agent._load_tester.run.assert_called_once()

    def test_coverage_report_dispatches(self, agent):
        task = Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={"action": "coverage_report", "repo": "vance-core"},
        )
        agent._coverage.report.return_value = {"coverage_pct": 82.0, "low_coverage_files": []}
        result = agent.handle(task)
        assert result.success is True
        agent._coverage.report.assert_called_once()

    def test_health_check_true_when_db_ok(self, agent):
        agent._db.get_recent_runs.return_value = []
        assert agent.health_check() is True

    def test_health_check_false_on_db_error(self, agent):
        agent._db.get_recent_runs.side_effect = Exception("db down")
        assert agent.health_check() is False
