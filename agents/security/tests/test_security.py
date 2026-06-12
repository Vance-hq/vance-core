"""Security agent unit tests — no external services required."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from agents._base import AgentConfig
from agents.security.db import SecurityDB
from agents.security.uptime_monitor import UptimeMonitor
from agents.security.intrusion_detector import IntrusionDetector
from agents.security.vuln_scanner import VulnScanner
from agents.security.ssl_monitor import SSLMonitor
from agents.security.secrets_auditor import SecretsAuditor
from agents.security.access_reviewer import AccessReviewer
from agents.security.ddos_responder import DDoSResponder
from agents.security.backup_checker import BackupChecker
from shared.types import Task, AgentCapability


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task(action: str, payload: dict | None = None) -> Task:
    p = {"action": action}
    if payload:
        p.update(payload)
    return Task(id=str(uuid.uuid4()), agent=AgentCapability.SECURITY, payload=p)


def _cfg() -> dict:
    return {
        "uptime_targets": ["https://vance.so/health", "https://starpio.com/health"],
        "uptime_kuma_url": "http://kuma:3001",
        "uptime_timeout_s": 5,
        "cloudflare_zone_ids": ["zone_abc123"],
        "baseline_rps": 100.0,
        "ssl_domains": ["vance.so", "starpio.com"],
        "auto_renew_domains": ["vance.so"],
        "repos": [{"path": "/app/vance", "name": "vance"}],
        "access_review_services": ["github", "cloudflare"],
        "backup_max_age_hours": 25,
        "loki_url": "http://loki:3100",
    }


@pytest.fixture
def mock_db():
    return MagicMock(spec=SecurityDB)


@pytest.fixture
def cfg():
    return _cfg()


# ---------------------------------------------------------------------------
# TestSecurityDB
# ---------------------------------------------------------------------------

class TestSecurityDB:

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

    def test_log_uptime_returns_id(self):
        db = SecurityDB()
        row_id = str(uuid.uuid4())
        conn, cur = self._conn_mock(fetchone=(row_id,))
        with patch("agents.security.db.get_db", return_value=conn):
            result = db.log_uptime("https://vance.so/health", ok=True, status=200, response_time_ms=42)
        assert result == row_id

    def test_log_uptime_records_failure(self):
        db = SecurityDB()
        conn, cur = self._conn_mock(fetchone=(str(uuid.uuid4()),))
        with patch("agents.security.db.get_db", return_value=conn):
            db.log_uptime("https://vance.so/health", ok=False, error="connection refused")
        cur.execute.assert_called_once()

    def test_get_recent_downtime_returns_list(self):
        db = SecurityDB()
        rows = [{"service": "vance.so", "ok": False}]
        conn, cur = self._conn_mock(fetchall=rows)
        with patch("agents.security.db.get_db", return_value=conn):
            result = db.get_recent_downtime(hours=1)
        assert isinstance(result, list)

    def test_save_event_returns_id(self):
        db = SecurityDB()
        row_id = str(uuid.uuid4())
        conn, cur = self._conn_mock(fetchone=(row_id,))
        with patch("agents.security.db.get_db", return_value=conn):
            result = db.save_event(
                event_type="ip_blocked",
                severity="HIGH",
                source_ip="1.2.3.4",
                action_taken="cloudflare_block",
            )
        assert result == row_id

    def test_save_vulnerability_calls_insert(self):
        db = SecurityDB()
        row_id = str(uuid.uuid4())
        conn, cur = self._conn_mock(fetchone=(row_id,))
        with patch("agents.security.db.get_db", return_value=conn):
            db.save_vulnerability(
                repo="vance",
                package="lodash",
                severity="HIGH",
                scan_type="npm",
                cve_id="CVE-2021-23337",
                cvss_score=7.2,
            )
        cur.execute.assert_called_once()

    def test_get_open_vulns_filters_by_status(self):
        db = SecurityDB()
        conn, cur = self._conn_mock(fetchall=[])
        with patch("agents.security.db.get_db", return_value=conn):
            result = db.get_open_vulns(repo="vance")
        sql = cur.execute.call_args[0][0]
        assert "status = 'open'" in sql

    def test_upsert_ssl_cert_uses_on_conflict(self):
        db = SecurityDB()
        conn, cur = self._conn_mock()
        with patch("agents.security.db.get_db", return_value=conn):
            db.upsert_ssl_cert(domain="vance.so", expires_at=datetime.now(timezone.utc), auto_renew=True)
        sql = cur.execute.call_args[0][0]
        assert "ON CONFLICT" in sql

    def test_get_expiring_certs_passes_days_threshold(self):
        db = SecurityDB()
        conn, cur = self._conn_mock(fetchall=[])
        with patch("agents.security.db.get_db", return_value=conn):
            db.get_expiring_certs(within_days=7)
        sql = cur.execute.call_args[0][0]
        assert "expires_at" in sql

    def test_save_access_audit_returns_id(self):
        db = SecurityDB()
        row_id = str(uuid.uuid4())
        conn, cur = self._conn_mock(fetchone=(row_id,))
        with patch("agents.security.db.get_db", return_value=conn):
            result = db.save_access_audit(
                service="github",
                account="user@example.com",
                access_level="admin",
                flagged=True,
                flag_reason="stale_key",
            )
        assert result == row_id

    def test_get_flagged_accounts_filters_by_flagged(self):
        db = SecurityDB()
        conn, cur = self._conn_mock(fetchall=[])
        with patch("agents.security.db.get_db", return_value=conn):
            db.get_flagged_accounts()
        sql = cur.execute.call_args[0][0]
        assert "flagged = true" in sql


# ---------------------------------------------------------------------------
# TestUptimeMonitor
# ---------------------------------------------------------------------------

class TestUptimeMonitor:

    def test_check_targets_returns_per_url_result(self, mock_db, cfg):
        monitor = UptimeMonitor(mock_db, cfg)
        with patch("agents.security.uptime_monitor.httpx.Client") as mock_client_cls:
            resp = MagicMock()
            resp.is_success = True
            resp.status_code = 200
            mock_client_cls.return_value.__enter__.return_value.get.return_value = resp

            result = monitor.check_targets(["https://vance.so/health"])

        assert "https://vance.so/health" in result
        assert result["https://vance.so/health"]["ok"] is True

    def test_check_targets_logs_each_url_to_db(self, mock_db, cfg):
        monitor = UptimeMonitor(mock_db, cfg)
        targets = ["https://a.com/health", "https://b.com/health"]
        with patch("agents.security.uptime_monitor.httpx.Client") as mock_client_cls:
            resp = MagicMock(is_success=True, status_code=200)
            mock_client_cls.return_value.__enter__.return_value.get.return_value = resp
            monitor.check_targets(targets)

        assert mock_db.log_uptime.call_count == len(targets)

    def test_check_targets_records_failure_on_exception(self, mock_db, cfg):
        monitor = UptimeMonitor(mock_db, cfg)
        with patch("agents.security.uptime_monitor.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.side_effect = Exception("timeout")
            result = monitor.check_targets(["https://vance.so/health"])

        assert result["https://vance.so/health"]["ok"] is False
        mock_db.log_uptime.assert_called_once()
        call_kwargs = mock_db.log_uptime.call_args[1]
        assert call_kwargs["ok"] is False

    def test_check_all_combines_http_and_kuma(self, mock_db, cfg):
        monitor = UptimeMonitor(mock_db, cfg)
        with patch.object(monitor, "check_targets", return_value={"https://vance.so/health": {"ok": True}}) as m_http, \
             patch.object(monitor, "check_uptime_kuma", return_value={}) as m_kuma:
            result = monitor.check_all()

        m_http.assert_called_once()
        m_kuma.assert_called_once()
        assert "http" in result
        assert "kuma" in result

    def test_check_all_all_ok_when_no_failures(self, mock_db, cfg):
        monitor = UptimeMonitor(mock_db, cfg)
        with patch.object(monitor, "check_targets", return_value={"https://vance.so/health": {"ok": True}}), \
             patch.object(monitor, "check_uptime_kuma", return_value={}):
            result = monitor.check_all()

        assert result["all_ok"] is True

    def test_check_uptime_kuma_returns_empty_on_error(self, mock_db, cfg):
        monitor = UptimeMonitor(mock_db, cfg)
        with patch("agents.security.uptime_monitor.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.side_effect = Exception("unreachable")
            result = monitor.check_uptime_kuma()

        assert result == {}


# ---------------------------------------------------------------------------
# TestIntrusionDetector
# ---------------------------------------------------------------------------

class TestIntrusionDetector:

    def test_check_failed_logins_detects_brute_force(self, mock_db, cfg):
        detector = IntrusionDetector(mock_db, cfg)
        now = datetime.now(timezone.utc)
        entries = [
            {"ip": "10.0.0.1", "failed_login": True, "timestamp": (now - timedelta(minutes=i)).isoformat()}
            for i in range(7)
        ]
        result = detector.check_failed_logins(entries)
        assert "10.0.0.1" in result

    def test_check_failed_logins_ignores_spread_attempts(self, mock_db, cfg):
        detector = IntrusionDetector(mock_db, cfg)
        now = datetime.now(timezone.utc)
        entries = [
            {"ip": "10.0.0.2", "failed_login": True, "timestamp": (now - timedelta(hours=i)).isoformat()}
            for i in range(6)
        ]
        result = detector.check_failed_logins(entries)
        assert "10.0.0.2" not in result

    def test_check_attack_patterns_detects_sql_injection(self, mock_db, cfg):
        detector = IntrusionDetector(mock_db, cfg)
        entries = [
            {"ip": "1.2.3.4", "path": "/api/users?id=1' UNION SELECT * FROM users--", "request": "GET"}
        ]
        result = detector.check_attack_patterns(entries)
        assert len(result) == 1
        assert result[0]["type"] == "sql_injection"

    def test_check_attack_patterns_detects_xss(self, mock_db, cfg):
        detector = IntrusionDetector(mock_db, cfg)
        entries = [{"ip": "5.5.5.5", "path": "/search?q=<script>alert(1)</script>", "request": "GET"}]
        result = detector.check_attack_patterns(entries)
        assert any(h["type"] == "xss_attempt" for h in result)

    def test_check_port_scans_flags_rapid_multi_port_hits(self, mock_db, cfg):
        detector = IntrusionDetector(mock_db, cfg)
        now = datetime.now(timezone.utc).timestamp()
        entries = [
            {"ip": "9.9.9.9", "port": str(8000 + i), "timestamp": now + i}
            for i in range(12)
        ]
        result = detector.check_port_scans(entries)
        assert "9.9.9.9" in result

    def test_scan_auto_blocks_brute_force_ip(self, mock_db, cfg):
        detector = IntrusionDetector(mock_db, cfg)
        now = datetime.now(timezone.utc)
        entries = [
            {"ip": "3.3.3.3", "failed_login": True, "timestamp": now.isoformat()}
            for _ in range(7)
        ]
        with patch.object(detector, "block_ip", return_value=True) as mock_block:
            findings = detector.scan(entries)

        mock_block.assert_called_once_with("3.3.3.3", reason="auto: threshold exceeded")
        assert "3.3.3.3" in findings["blocked_ips"]

    def test_scan_saves_attack_pattern_events(self, mock_db, cfg):
        detector = IntrusionDetector(mock_db, cfg)
        entries = [{"ip": "7.7.7.7", "path": "/api?q=' OR 1=1--", "request": "GET"}]
        with patch.object(detector, "block_ip", return_value=False):
            detector.scan(entries)

        mock_db.save_event.assert_called()

    def test_triage_with_llm_returns_string(self, mock_db, cfg):
        detector = IntrusionDetector(mock_db, cfg)
        entries = [{"ip": "2.2.2.2", "path": "/api", "status": 403}]
        with patch("agents.security.intrusion_detector.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text="This looks like normal traffic.")]
            result = detector.triage_with_llm(entries)

        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# TestVulnScanner
# ---------------------------------------------------------------------------

class TestVulnScanner:

    def test_classify_critical_cvss(self, mock_db, cfg):
        scanner = VulnScanner(mock_db, cfg)
        assert scanner.classify({"cvss_score": 9.8}) == "CRITICAL"

    def test_classify_high_cvss(self, mock_db, cfg):
        scanner = VulnScanner(mock_db, cfg)
        assert scanner.classify({"cvss_score": 7.5}) == "HIGH"

    def test_classify_medium_cvss(self, mock_db, cfg):
        scanner = VulnScanner(mock_db, cfg)
        assert scanner.classify({"cvss_score": 5.0}) == "MEDIUM"

    def test_classify_low_cvss(self, mock_db, cfg):
        scanner = VulnScanner(mock_db, cfg)
        assert scanner.classify({"cvss_score": 2.0}) == "LOW"

    def test_scan_npm_returns_empty_on_missing_binary(self, mock_db, cfg):
        scanner = VulnScanner(mock_db, cfg)
        with patch("agents.security.vuln_scanner.subprocess.run", side_effect=FileNotFoundError):
            result = scanner.scan_npm("/app/vance")
        assert result == []

    def test_scan_pip_returns_empty_on_timeout(self, mock_db, cfg):
        scanner = VulnScanner(mock_db, cfg)
        import subprocess as sp
        with patch("agents.security.vuln_scanner.subprocess.run", side_effect=sp.TimeoutExpired("pip-audit", 180)):
            result = scanner.scan_pip("/app/vance")
        assert result == []

    def test_process_repo_saves_findings_to_db(self, mock_db, cfg):
        scanner = VulnScanner(mock_db, cfg)
        npm_findings = [{"package": "lodash", "scan_type": "npm", "cvss_score": 7.5, "cve_id": "CVE-2021-1"}]
        with patch.object(scanner, "scan_npm", return_value=npm_findings), \
             patch.object(scanner, "scan_pip", return_value=[]):
            scanner.process_repo("/app/vance", "vance")

        mock_db.save_vulnerability.assert_called_once()

    def test_process_repo_returns_findings_by_severity(self, mock_db, cfg):
        scanner = VulnScanner(mock_db, cfg)
        findings = [
            {"package": "a", "scan_type": "npm", "cvss_score": 9.5, "cve_id": None},
            {"package": "b", "scan_type": "npm", "cvss_score": 7.0, "cve_id": None},
        ]
        with patch.object(scanner, "scan_npm", return_value=findings), \
             patch.object(scanner, "scan_pip", return_value=[]):
            result = scanner.process_repo("/app/vance", "vance")

        assert len(result["CRITICAL"]) == 1
        assert len(result["HIGH"]) == 1
        assert result["total"] == 2


# ---------------------------------------------------------------------------
# TestSSLMonitor
# ---------------------------------------------------------------------------

class TestSSLMonitor:

    def _make_cert(self, days_remaining: int) -> dict:
        expiry = datetime.now(timezone.utc) + timedelta(days=days_remaining)
        return {
            "notAfter": expiry.strftime("%b %d %H:%M:%S %Y GMT"),
            "issuer": ((("commonName", "Let's Encrypt"),),),
        }

    def test_check_domain_returns_days_remaining(self, mock_db, cfg):
        monitor = SSLMonitor(mock_db, cfg)
        fake_cert = self._make_cert(45)
        with patch("agents.security.ssl_monitor.socket.create_connection") as mock_conn, \
             patch("agents.security.ssl_monitor.ssl.create_default_context") as mock_ctx:
            mock_ctx.return_value.wrap_socket.return_value.__enter__ = MagicMock(
                return_value=MagicMock(getpeercert=MagicMock(return_value=fake_cert))
            )
            mock_ctx.return_value.wrap_socket.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)

            result = monitor.check_domain("vance.so")

        assert result["ok"] is True
        assert "days_remaining" in result

    def test_check_domain_returns_error_on_failure(self, mock_db, cfg):
        monitor = SSLMonitor(mock_db, cfg)
        with patch("agents.security.ssl_monitor.socket.create_connection", side_effect=Exception("timeout")):
            result = monitor.check_domain("vance.so")

        assert result["ok"] is False
        assert "error" in result

    def test_check_domain_upserts_ssl_cert_record(self, mock_db, cfg):
        monitor = SSLMonitor(mock_db, cfg)
        with patch("agents.security.ssl_monitor.socket.create_connection", side_effect=Exception("no route")):
            monitor.check_domain("vance.so")

        mock_db.upsert_ssl_cert.assert_called_once()

    def test_check_all_includes_expiring_in_result(self, mock_db, cfg):
        monitor = SSLMonitor(mock_db, cfg)
        with patch.object(monitor, "check_domain") as mock_check:
            mock_check.side_effect = [
                {"domain": "vance.so", "ok": True, "days_remaining": 5},
                {"domain": "starpio.com", "ok": True, "days_remaining": 60},
            ]
            result = monitor.check_all()

        assert "vance.so" in result["expiring"]
        assert "starpio.com" not in result["expiring"]

    def test_check_all_attempts_auto_renew_for_configured_domains(self, mock_db, cfg):
        monitor = SSLMonitor(mock_db, cfg)
        with patch.object(monitor, "check_domain", return_value={"domain": "vance.so", "ok": True, "days_remaining": 3}), \
             patch.object(monitor, "auto_renew", return_value=True) as mock_renew:
            monitor.check_all()

        mock_renew.assert_called_once_with("vance.so")

    def test_auto_renew_returns_false_when_certbot_missing(self, mock_db, cfg):
        monitor = SSLMonitor(mock_db, cfg)
        with patch("agents.security.ssl_monitor.subprocess.run", side_effect=FileNotFoundError):
            result = monitor.auto_renew("vance.so")

        assert result is False


# ---------------------------------------------------------------------------
# TestSecretsAuditor
# ---------------------------------------------------------------------------

class TestSecretsAuditor:

    def test_scan_repo_strips_secret_values(self, mock_db, cfg):
        auditor = SecretsAuditor(mock_db, cfg)
        raw_finding = [{"RuleID": "aws-access-token", "File": "config.py", "Secret": "AKIA...", "Match": "AKIA...", "Commit": "abc123"}]
        with patch("agents.security.secrets_auditor.subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(raw_finding)
            mock_run.return_value.returncode = 1
            result = auditor.scan_repo("/app/vance")

        assert len(result) == 1
        assert result[0]["Secret"] == "[REDACTED]"
        assert result[0]["Match"] == "[REDACTED]"

    def test_scan_repo_returns_empty_when_gitleaks_missing(self, mock_db, cfg):
        auditor = SecretsAuditor(mock_db, cfg)
        with patch("agents.security.secrets_auditor.subprocess.run", side_effect=FileNotFoundError):
            result = auditor.scan_repo("/app/vance")

        assert result == []

    def test_assess_severity_returns_valid_label(self, mock_db, cfg):
        auditor = SecretsAuditor(mock_db, cfg)
        finding = {"RuleID": "stripe-secret-key", "File": "settings.py", "Commit": "def456"}
        with patch("agents.security.secrets_auditor.llm") as mock_llm:
            mock_llm.complete.return_value.content = [MagicMock(text="CRITICAL")]
            result = auditor.assess_severity(finding)

        assert result == "CRITICAL"

    def test_assess_severity_defaults_to_high_on_llm_error(self, mock_db, cfg):
        auditor = SecretsAuditor(mock_db, cfg)
        finding = {"RuleID": "generic-api-key", "File": "env.py"}
        with patch("agents.security.secrets_auditor.llm") as mock_llm:
            mock_llm.complete.side_effect = Exception("LLM unavailable")
            result = auditor.assess_severity(finding)

        assert result == "HIGH"

    def test_scan_all_repos_saves_critical_event_per_finding(self, mock_db, cfg):
        auditor = SecretsAuditor(mock_db, cfg)
        raw = [{"RuleID": "stripe-secret-key", "File": "main.py", "Secret": "sk_live_xxx", "Match": "sk_live_xxx", "Commit": "abc"}]
        with patch.object(auditor, "scan_repo", return_value=[auditor._sanitize(raw[0])]), \
             patch.object(auditor, "assess_severity", return_value="CRITICAL"):
            result = auditor.scan_all_repos()

        mock_db.save_event.assert_called_once()
        assert result["total"] == 1

    def test_secrets_not_logged_in_event_details(self, mock_db, cfg):
        auditor = SecretsAuditor(mock_db, cfg)
        raw = [{"RuleID": "stripe-secret-key", "File": "main.py", "Secret": "sk_live_REAL", "Match": "sk_live_REAL", "Commit": "abc"}]
        with patch.object(auditor, "scan_repo", return_value=[auditor._sanitize(raw[0])]), \
             patch.object(auditor, "assess_severity", return_value="CRITICAL"):
            auditor.scan_all_repos()

        call_kwargs = mock_db.save_event.call_args[1]
        details_str = json.dumps(call_kwargs.get("details", {}))
        assert "sk_live_REAL" not in details_str


# ---------------------------------------------------------------------------
# TestAccessReviewer
# ---------------------------------------------------------------------------

class TestAccessReviewer:

    def test_flag_stale_keys_flags_old_accounts(self, mock_db, cfg):
        reviewer = AccessReviewer(mock_db, cfg)
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        accounts = [{"service": "github", "account": "oldbot", "access_level": "read", "last_used": old_date}]

        flagged = reviewer.flag_stale_keys(accounts)

        assert len(flagged) == 1
        assert flagged[0]["account"] == "oldbot"

    def test_flag_stale_keys_does_not_flag_recent_accounts(self, mock_db, cfg):
        reviewer = AccessReviewer(mock_db, cfg)
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        accounts = [{"service": "github", "account": "activedep", "access_level": "admin", "last_used": recent}]

        flagged = reviewer.flag_stale_keys(accounts)

        assert len(flagged) == 0

    def test_flag_stale_keys_saves_each_account_to_db(self, mock_db, cfg):
        reviewer = AccessReviewer(mock_db, cfg)
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        accounts = [
            {"service": "github", "account": "user1", "access_level": "read", "last_used": recent},
            {"service": "github", "account": "user2", "access_level": "admin", "last_used": recent},
        ]
        reviewer.flag_stale_keys(accounts)

        assert mock_db.save_access_audit.call_count == 2

    def test_review_service_unknown_returns_empty(self, mock_db, cfg):
        reviewer = AccessReviewer(mock_db, cfg)
        result = reviewer.review_service("nonexistent_service")
        assert result == []

    def test_review_all_iterates_configured_services(self, mock_db, cfg):
        reviewer = AccessReviewer(mock_db, cfg)
        with patch.object(reviewer, "review_service", return_value=[]) as mock_review:
            reviewer.review_all()

        assert mock_review.call_count == len(cfg["access_review_services"])


# ---------------------------------------------------------------------------
# TestDDoSResponder
# ---------------------------------------------------------------------------

class TestDDoSResponder:

    def test_is_attack_returns_true_on_10x_spike_with_automation(self, mock_db, cfg):
        responder = DDoSResponder(mock_db, cfg)
        # 100 rps baseline, 1200 rps = 12x; 1 unique IP = automated
        metrics = {"rps": 1200.0, "requests_5min": 360000, "unique_ips": 1}
        assert responder.is_attack(metrics, {"baseline_rps": 100.0}) is True

    def test_is_attack_returns_false_below_threshold(self, mock_db, cfg):
        responder = DDoSResponder(mock_db, cfg)
        metrics = {"rps": 150.0, "requests_5min": 45000, "unique_ips": 500}
        assert responder.is_attack(metrics, {"baseline_rps": 100.0}) is False

    def test_is_attack_requires_automated_pattern(self, mock_db, cfg):
        responder = DDoSResponder(mock_db, cfg)
        # 10x spike but from 5000 unique IPs = organic surge, not automated
        metrics = {"rps": 1200.0, "requests_5min": 360000, "unique_ips": 5000}
        assert responder.is_attack(metrics, {"baseline_rps": 100.0}) is False

    def test_respond_enables_under_attack_on_ddos(self, mock_db, cfg):
        responder = DDoSResponder(mock_db, cfg)
        spike_metrics = {"rps": 2000.0, "requests_5min": 600000, "unique_ips": 2, "zone_id": "zone_abc123"}
        with patch.object(responder, "check_traffic", return_value=spike_metrics), \
             patch.object(responder, "enable_under_attack", return_value=True) as mock_ua, \
             patch.object(responder, "_create_rate_limit_rule"):
            responder.respond()

        mock_ua.assert_called_once_with("zone_abc123")

    def test_respond_logs_attack_event(self, mock_db, cfg):
        responder = DDoSResponder(mock_db, cfg)
        spike = {"rps": 2000.0, "requests_5min": 600000, "unique_ips": 1, "zone_id": "zone_abc123"}
        with patch.object(responder, "check_traffic", return_value=spike), \
             patch.object(responder, "enable_under_attack", return_value=True), \
             patch.object(responder, "_create_rate_limit_rule"):
            responder.respond()

        mock_db.save_event.assert_called_once()
        call_kwargs = mock_db.save_event.call_args[1]
        assert call_kwargs["event_type"] == "ddos_detected"
        assert call_kwargs["severity"] == "CRITICAL"

    def test_disable_under_attack_logs_mitigation_event(self, mock_db, cfg):
        responder = DDoSResponder(mock_db, cfg)
        with patch.object(responder, "_set_security_level", return_value=True):
            responder.disable_under_attack("zone_abc123")

        mock_db.save_event.assert_called_once()
        call_kwargs = mock_db.save_event.call_args[1]
        assert call_kwargs["event_type"] == "ddos_mitigated"

    def test_respond_returns_zero_attacks_when_no_zones(self, mock_db, cfg):
        responder = DDoSResponder(mock_db, {**cfg, "cloudflare_zone_ids": []})
        result = responder.respond()
        assert result["zones_checked"] == 0
        assert result["attacks_detected"] == 0


# ---------------------------------------------------------------------------
# TestBackupChecker
# ---------------------------------------------------------------------------

class TestBackupChecker:

    def test_check_ok_when_recent_backup(self, mock_db, cfg):
        checker = BackupChecker(mock_db, cfg)
        mock_db.get_last_backup_timestamp.return_value = datetime.now(timezone.utc) - timedelta(hours=2)
        result = checker.check()
        assert result["ok"] is True
        assert result["age_hours"] < 25

    def test_check_fails_when_backup_stale(self, mock_db, cfg):
        checker = BackupChecker(mock_db, cfg)
        mock_db.get_last_backup_timestamp.return_value = datetime.now(timezone.utc) - timedelta(hours=30)
        result = checker.check()
        assert result["ok"] is False
        assert result["age_hours"] > 25

    def test_check_fails_when_no_backup_record(self, mock_db, cfg):
        checker = BackupChecker(mock_db, cfg)
        mock_db.get_last_backup_timestamp.return_value = None
        result = checker.check()
        assert result["ok"] is False
        assert result["last_backup"] is None

    def test_check_returns_age_in_hours(self, mock_db, cfg):
        checker = BackupChecker(mock_db, cfg)
        mock_db.get_last_backup_timestamp.return_value = datetime.now(timezone.utc) - timedelta(hours=10)
        result = checker.check()
        assert 9 < result["age_hours"] < 11


# ---------------------------------------------------------------------------
# TestSecurityAgent — full dispatch
# ---------------------------------------------------------------------------

class TestSecurityAgent:

    def _make_agent(self):
        from agents.security.main import SecurityAgent

        config = MagicMock(spec=AgentConfig)
        config.custom = _cfg()
        config.llm_system_prompt = None
        return SecurityAgent("security", config)

    def test_unknown_action_returns_error(self):
        agent = self._make_agent()
        result = agent.handle(_task("not_a_real_action"))
        assert result.success is False
        assert "error" in result.output

    def test_uptime_monitor_dispatches(self):
        agent = self._make_agent()
        with patch.object(agent._uptime, "check_all", return_value={"all_ok": True, "failures": [], "http": {}, "kuma": {}}) as m:
            result = agent.handle(_task("uptime_monitor"))
        m.assert_called_once()
        assert result.success is True

    def test_uptime_monitor_fires_critical_alert_on_failure(self):
        agent = self._make_agent()
        with patch.object(agent._uptime, "check_all", return_value={"all_ok": False, "failures": ["https://vance.so/health"], "http": {}, "kuma": {}}), \
             patch.object(agent, "_critical_alert") as mock_alert:
            agent.handle(_task("uptime_monitor"))
        mock_alert.assert_called_once()

    def test_intrusion_detect_dispatches(self):
        agent = self._make_agent()
        entries = [{"ip": "1.2.3.4", "path": "/api", "status": 200}]
        with patch.object(agent._intrusion, "scan", return_value={"blocked_ips": [], "attack_patterns": [], "llm_triage": None}) as m:
            result = agent.handle(_task("intrusion_detect", {"log_entries": entries}))
        m.assert_called_once_with(entries)
        assert result.success is True

    def test_intrusion_detect_fires_critical_alert_on_block(self):
        agent = self._make_agent()
        with patch.object(agent._intrusion, "scan", return_value={"blocked_ips": ["6.6.6.6"], "attack_patterns": [], "llm_triage": None}), \
             patch.object(agent, "_critical_alert") as mock_alert:
            agent.handle(_task("intrusion_detect", {"log_entries": []}))
        mock_alert.assert_called_once()

    def test_vulnerability_scan_dispatches(self):
        agent = self._make_agent()
        with patch.object(agent._vuln, "scan_all_repos", return_value=[]) as m:
            result = agent.handle(_task("vulnerability_scan"))
        m.assert_called_once()
        assert result.success is True

    def test_ssl_cert_monitor_dispatches(self):
        agent = self._make_agent()
        with patch.object(agent._ssl, "check_all", return_value={"domains": {}, "expiring": []}) as m:
            result = agent.handle(_task("ssl_cert_monitor"))
        m.assert_called_once()
        assert result.success is True

    def test_secrets_audit_dispatches(self):
        agent = self._make_agent()
        with patch.object(agent._secrets, "scan_all_repos", return_value={"findings": [], "total": 0}) as m:
            result = agent.handle(_task("secrets_audit"))
        m.assert_called_once()
        assert result.success is True

    def test_access_review_dispatches(self):
        agent = self._make_agent()
        with patch.object(agent._access, "review_all", return_value={"flagged": [], "per_service": {}, "total_flagged": 0}) as m:
            result = agent.handle(_task("access_review"))
        m.assert_called_once()
        assert result.success is True

    def test_ddos_response_dispatches(self):
        agent = self._make_agent()
        with patch.object(agent._ddos, "respond", return_value={"zones_checked": 1, "attacks_detected": 0}) as m:
            result = agent.handle(_task("ddos_response"))
        m.assert_called_once()
        assert result.success is True

    def test_ddos_response_fires_critical_alert_on_attack(self):
        agent = self._make_agent()
        with patch.object(agent._ddos, "respond", return_value={"zones_checked": 1, "attacks_detected": 1}), \
             patch.object(agent, "_critical_alert") as mock_alert:
            agent.handle(_task("ddos_response"))
        mock_alert.assert_called_once()

    def test_backup_integrity_check_dispatches(self):
        agent = self._make_agent()
        with patch.object(agent._backup, "check", return_value={"ok": True, "age_hours": 5.0, "last_backup": "2026-06-12T12:00:00+00:00"}) as m:
            result = agent.handle(_task("backup_integrity_check"))
        m.assert_called_once()
        assert result.success is True

    def test_backup_integrity_fires_critical_alert_on_stale(self):
        agent = self._make_agent()
        with patch.object(agent._backup, "check", return_value={"ok": False, "age_hours": 30.0, "reason": "too old"}), \
             patch.object(agent, "_critical_alert") as mock_alert:
            agent.handle(_task("backup_integrity_check"))
        mock_alert.assert_called_once()

    def test_critical_alert_publishes_to_redis(self):
        agent = self._make_agent()
        with patch.object(agent._redis, "publish") as mock_pub:
            agent._critical_alert("test_event", "Test message")
        mock_pub.assert_called_once()
        channel, payload = mock_pub.call_args[0]
        assert channel == "vance:security:alerts"
        data = json.loads(payload)
        assert data["severity"] == "CRITICAL"
        assert data["event_type"] == "test_event"

    def test_health_check_true_when_db_ok(self):
        agent = self._make_agent()
        with patch.object(agent._db, "get_events", return_value=[]):
            assert agent.health_check() is True

    def test_health_check_false_on_db_error(self):
        agent = self._make_agent()
        with patch.object(agent._db, "get_events", side_effect=Exception("db down")):
            assert agent.health_check() is False
