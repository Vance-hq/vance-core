"""Behavioral tests for the backup agent."""

from __future__ import annotations

import base64
import io
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

# 32-byte AES-256 key, base64-encoded
_TEST_KEY_B64 = base64.b64encode(b"A" * 32).decode()

_CFG = {
    "encryption_key": _TEST_KEY_B64,
    "backup_paths": ["/fake/uploads", "/fake/config"],
    "log_path": "/fake/logs",
    "dump_timeout_s": 60,
    "restore_timeout_s": 60,
    "test_schema": "backup_test",
    "restore_min_counts": {"tasks": 0},
    "mailcow_host": "mail.example.com",
    "mailcow_api_key": "test-api-key",
}


def _task(action: str, **payload):
    from shared.types import AgentCapability, Task
    return Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.BACKUP,
        payload={"action": action, **payload},
    )


def _agent():
    from agents._base import AgentConfig
    from agents.backup.main import BackupAgent

    raw = {
        "agent_name": "backup",
        "enabled": True,
        "poll_interval_seconds": 5.0,
        "max_retries": 3,
        "llm_system_prompt": "",
        "custom": _CFG,
    }
    config = AgentConfig(**raw)
    with (
        patch("agents.backup.main.BackupDB"),
        patch("agents.backup.main.PostgresBackup"),
        patch("agents.backup.main.FileBackup"),
        patch("agents.backup.main.MailcowBackup"),
        patch("agents.backup.main.RestoreVerifier"),
        patch("agents.backup.main.BaseAgent.__init__", lambda *a, **kw: None),
    ):
        agent = BackupAgent.__new__(BackupAgent)
        agent.agent_name = "backup"
        agent.config = config
        agent._db = MagicMock()
        agent._pg = MagicMock()
        agent._files = MagicMock()
        agent._mailcow = MagicMock()
        agent._verifier = MagicMock()
        agent._dispatch = {
            "backup_postgres": agent._backup_postgres,
            "backup_files": agent._backup_files,
            "verify_restore": agent._verify_restore,
            "mailcow_backup": agent._mailcow_backup,
        }
        return agent


# ---------------------------------------------------------------------------
# BackupAgent — routing
# ---------------------------------------------------------------------------

class TestBackupAgentRouting:
    def test_unknown_action_returns_failure(self):
        agent = _agent()
        result = agent.handle(_task("nonexistent"))
        assert result.success is False
        assert "unknown action" in result.error

    def test_backup_postgres_routes_correctly(self):
        agent = _agent()
        agent._pg.run.return_value = {"keys": [], "size_bytes": 100}
        result = agent.handle(_task("backup_postgres"))
        assert result.success is True
        agent._pg.run.assert_called_once()

    def test_backup_files_routes_correctly(self):
        agent = _agent()
        agent._files.run.return_value = {"keys": [], "size_bytes": 200}
        result = agent.handle(_task("backup_files"))
        assert result.success is True
        agent._files.run.assert_called_once()

    def test_verify_restore_routes_correctly(self):
        agent = _agent()
        agent._verifier.verify.return_value = {"success": True}
        result = agent.handle(_task("verify_restore"))
        assert result.success is True
        agent._verifier.verify.assert_called_once()

    def test_mailcow_backup_routes_correctly(self):
        agent = _agent()
        agent._mailcow.run.return_value = {"key": "backups/mailcow/..."}
        result = agent.handle(_task("mailcow_backup"))
        assert result.success is True
        agent._mailcow.run.assert_called_once()

    def test_exception_in_handler_returns_failure(self):
        agent = _agent()
        agent._pg.run.side_effect = RuntimeError("pg_dump failed")
        result = agent.handle(_task("backup_postgres"))
        assert result.success is False
        assert "pg_dump failed" in result.error


# ---------------------------------------------------------------------------
# BackupAgent — health_check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_check_true_when_db_ok(self):
        agent = _agent()
        agent._db.get_last_backup.return_value = {"backup_type": "postgres"}
        assert agent.health_check() is True

    def test_health_check_false_when_db_fails(self):
        agent = _agent()
        agent._db.get_last_backup.side_effect = Exception("db down")
        assert agent.health_check() is False


# ---------------------------------------------------------------------------
# BackupEncryptor
# ---------------------------------------------------------------------------

class TestBackupEncryptor:
    def test_encrypt_then_decrypt_roundtrip(self):
        from agents.backup.encryptor import BackupEncryptor
        enc = BackupEncryptor(_TEST_KEY_B64)
        plaintext = b"Hello, backup world!"
        ciphertext = enc.encrypt(plaintext)
        assert enc.decrypt(ciphertext) == plaintext

    def test_encrypt_produces_different_output_each_call(self):
        from agents.backup.encryptor import BackupEncryptor
        enc = BackupEncryptor(_TEST_KEY_B64)
        ct1 = enc.encrypt(b"same data")
        ct2 = enc.encrypt(b"same data")
        # Different nonces → different ciphertexts
        assert ct1 != ct2

    def test_wrong_key_length_raises(self):
        from agents.backup.encryptor import BackupEncryptor
        bad_key = base64.b64encode(b"short").decode()
        with pytest.raises(ValueError, match="32 bytes"):
            BackupEncryptor(bad_key)

    def test_ciphertext_is_longer_than_plaintext(self):
        from agents.backup.encryptor import BackupEncryptor
        enc = BackupEncryptor(_TEST_KEY_B64)
        ct = enc.encrypt(b"data")
        # nonce (12) + GCM tag (16) + data (4) = 32 minimum
        assert len(ct) > len(b"data")

    def test_tampered_ciphertext_raises_on_decrypt(self):
        from agents.backup.encryptor import BackupEncryptor
        from cryptography.exceptions import InvalidTag
        enc = BackupEncryptor(_TEST_KEY_B64)
        ct = bytearray(enc.encrypt(b"important data"))
        ct[-1] ^= 0xFF  # flip a bit in the GCM tag
        with pytest.raises(InvalidTag):
            enc.decrypt(bytes(ct))


# ---------------------------------------------------------------------------
# PostgresBackup
# ---------------------------------------------------------------------------

class TestPostgresBackup:
    def _backup(self, db=None):
        from agents.backup.postgres_backup import PostgresBackup
        return PostgresBackup(_CFG, db or MagicMock())

    def test_successful_backup_uploads_daily_key(self):
        db = MagicMock()
        with (
            patch("agents.backup.postgres_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.postgres_backup.subprocess.run") as mock_run,
            patch("agents.backup.postgres_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.postgres_backup.tempfile.NamedTemporaryFile") as MockTmp,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            MockEnc.return_value.encrypt.return_value = b"encrypted_data"
            tmp = MagicMock()
            tmp.__enter__ = lambda s: s
            tmp.__exit__ = MagicMock(return_value=False)
            tmp.read.return_value = b"dump_data"
            tmp.name = "/tmp/fake.dump"
            MockTmp.return_value = tmp
            MockB2.return_value.list_files.return_value = []
            backup = self._backup(db)
            result = backup.run()
        today = str(date.today())
        assert any(today in k for k in result["keys"])
        assert "daily" in result["keys"][0]

    def test_weekly_key_created_on_monday(self):
        db = MagicMock()
        monday = date(2026, 6, 15)  # A known Monday (weekday == 0)
        with (
            patch("agents.backup.postgres_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.postgres_backup.subprocess.run"),
            patch("agents.backup.postgres_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.postgres_backup.date") as mock_date,
            patch("agents.backup.postgres_backup.tempfile.NamedTemporaryFile") as MockTmp,
        ):
            mock_date.today.return_value = monday
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            MockEnc.return_value.encrypt.return_value = b"enc"
            tmp = MagicMock()
            tmp.__enter__ = lambda s: s
            tmp.__exit__ = MagicMock(return_value=False)
            tmp.read.return_value = b"dump"
            tmp.name = "/tmp/fake.dump"
            MockTmp.return_value = tmp
            MockB2.return_value.list_files.return_value = []
            backup = self._backup(db)
            result = backup.run()
        assert any("weekly" in k for k in result["keys"])

    def test_monthly_key_created_on_first_of_month(self):
        db = MagicMock()
        first = date(2026, 6, 1)  # weekday = 0 (Monday), day = 1
        with (
            patch("agents.backup.postgres_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.postgres_backup.subprocess.run"),
            patch("agents.backup.postgres_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.postgres_backup.date") as mock_date,
            patch("agents.backup.postgres_backup.tempfile.NamedTemporaryFile") as MockTmp,
        ):
            mock_date.today.return_value = first
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            MockEnc.return_value.encrypt.return_value = b"enc"
            tmp = MagicMock()
            tmp.__enter__ = lambda s: s
            tmp.__exit__ = MagicMock(return_value=False)
            tmp.read.return_value = b"dump"
            tmp.name = "/tmp/fake.dump"
            MockTmp.return_value = tmp
            MockB2.return_value.list_files.return_value = []
            backup = self._backup(db)
            result = backup.run()
        assert any("monthly" in k for k in result["keys"])

    def test_backup_logged_to_db(self):
        db = MagicMock()
        with (
            patch("agents.backup.postgres_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.postgres_backup.subprocess.run"),
            patch("agents.backup.postgres_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.postgres_backup.tempfile.NamedTemporaryFile") as MockTmp,
        ):
            MockEnc.return_value.encrypt.return_value = b"encrypted"
            tmp = MagicMock()
            tmp.__enter__ = lambda s: s
            tmp.__exit__ = MagicMock(return_value=False)
            tmp.read.return_value = b"dump"
            tmp.name = "/tmp/fake.dump"
            MockTmp.return_value = tmp
            MockB2.return_value.list_files.return_value = []
            backup = self._backup(db)
            backup.run()
        db.insert_log.assert_called_once()
        call_kwargs = db.insert_log.call_args[1]
        assert call_kwargs["backup_type"] == "postgres"
        assert call_kwargs["size_bytes"] == len(b"encrypted")

    def test_pg_dump_failure_logs_error_and_raises(self):
        db = MagicMock()
        with (
            patch("agents.backup.postgres_backup.BackblazeConnector"),
            patch("agents.backup.postgres_backup.subprocess.run") as mock_run,
            patch("agents.backup.postgres_backup.BackupEncryptor"),
            patch("agents.backup.postgres_backup.tempfile.NamedTemporaryFile") as MockTmp,
        ):
            tmp = MagicMock()
            tmp.__enter__ = lambda s: s
            tmp.__exit__ = MagicMock(return_value=False)
            tmp.name = "/tmp/fake.dump"
            MockTmp.return_value = tmp
            mock_run.side_effect = Exception("pg_dump not found")
            backup = self._backup(db)
            with pytest.raises(Exception, match="pg_dump not found"):
                backup.run()
        db.insert_log.assert_called_once()
        assert db.insert_log.call_args[1]["error"] == "pg_dump not found"

    def test_prune_deletes_old_daily_backups(self):
        db = MagicMock()
        old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        with (
            patch("agents.backup.postgres_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.postgres_backup.subprocess.run"),
            patch("agents.backup.postgres_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.postgres_backup.tempfile.NamedTemporaryFile") as MockTmp,
        ):
            MockEnc.return_value.encrypt.return_value = b"enc"
            tmp = MagicMock()
            tmp.__enter__ = lambda s: s
            tmp.__exit__ = MagicMock(return_value=False)
            tmp.read.return_value = b"dump"
            tmp.name = "/tmp/fake.dump"
            MockTmp.return_value = tmp
            MockB2.return_value.list_files.return_value = [
                {"key": "backups/postgres/daily/old.sql.gz.enc", "last_modified": old_ts}
            ]
            backup = self._backup(db)
            backup.run()
        MockB2.return_value.delete_file.assert_called()

    def test_parse_db_name_extracts_correctly(self):
        from agents.backup.postgres_backup import PostgresBackup
        assert PostgresBackup._parse_db_name("postgres://user:pass@host/mydb") == "mydb"
        assert PostgresBackup._parse_db_name("postgres://host/mydb?sslmode=require") == "mydb"
        assert PostgresBackup._parse_db_name("") == "vance"


# ---------------------------------------------------------------------------
# FileBackup
# ---------------------------------------------------------------------------

class TestFileBackup:
    def _backup(self, db=None):
        from agents.backup.file_backup import FileBackup
        return FileBackup(_CFG, db or MagicMock())

    def test_successful_run_uploads_encrypted_archive(self):
        db = MagicMock()
        with (
            patch("agents.backup.file_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.file_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.file_backup.os.path.exists", return_value=False),
            patch("agents.backup.file_backup.os.path.isdir", return_value=False),
        ):
            MockEnc.return_value.encrypt.return_value = b"encrypted_archive"
            MockB2.return_value.list_files.return_value = []
            backup = self._backup(db)
            result = backup.run()
        assert "keys" in result
        assert len(result["keys"]) >= 1
        assert "daily" in result["keys"][0]

    def test_archive_is_logged_to_db(self):
        db = MagicMock()
        with (
            patch("agents.backup.file_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.file_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.file_backup.os.path.exists", return_value=False),
            patch("agents.backup.file_backup.os.path.isdir", return_value=False),
        ):
            MockEnc.return_value.encrypt.return_value = b"enc"
            MockB2.return_value.list_files.return_value = []
            backup = self._backup(db)
            backup.run()
        db.insert_log.assert_called_once()
        assert db.insert_log.call_args[1]["backup_type"] == "files"

    def test_size_bytes_matches_encrypted_length(self):
        db = MagicMock()
        with (
            patch("agents.backup.file_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.file_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.file_backup.os.path.exists", return_value=False),
            patch("agents.backup.file_backup.os.path.isdir", return_value=False),
        ):
            MockEnc.return_value.encrypt.return_value = b"X" * 1024
            MockB2.return_value.list_files.return_value = []
            backup = self._backup(db)
            result = backup.run()
        assert result["size_bytes"] == 1024

    def test_create_archive_includes_existing_paths(self):
        import tempfile as tmpmod
        db = MagicMock()
        with tmpmod.TemporaryDirectory() as tmpdir:
            # Create a test file in tmpdir
            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, "w") as f:
                f.write("hello")
            cfg = dict(_CFG)
            cfg["backup_paths"] = [tmpdir]
            cfg["log_path"] = "/nonexistent"
            from agents.backup.file_backup import FileBackup
            backup = FileBackup(cfg, db)
            archive_bytes = backup._create_archive()
        # Should produce a valid tar.gz
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
            names = tar.getnames()
        assert any("test.txt" in n for n in names)

    def test_logs_older_than_30_days_excluded(self):
        import tempfile as tmpmod
        db = MagicMock()
        with tmpmod.TemporaryDirectory() as tmpdir:
            old_file = os.path.join(tmpdir, "old.log")
            with open(old_file, "w") as f:
                f.write("old log")
            # Set mtime to 40 days ago
            old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()
            os.utime(old_file, (old_ts, old_ts))

            new_file = os.path.join(tmpdir, "new.log")
            with open(new_file, "w") as f:
                f.write("new log")

            cfg = dict(_CFG)
            cfg["backup_paths"] = []
            cfg["log_path"] = tmpdir
            from agents.backup.file_backup import FileBackup
            backup = FileBackup(cfg, db)
            archive_bytes = backup._create_archive()

        import tarfile
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
            names = tar.getnames()

        assert any("new.log" in n for n in names)
        assert not any("old.log" in n for n in names)


# ---------------------------------------------------------------------------
# RestoreVerifier
# ---------------------------------------------------------------------------

class TestRestoreVerifier:
    def _verifier(self, db=None):
        from agents.backup.restore_verifier import RestoreVerifier
        return RestoreVerifier(_CFG, db or MagicMock())

    def test_returns_no_recent_backups_when_db_empty(self):
        db = MagicMock()
        db.get_recent_backups.return_value = []
        verifier = self._verifier(db)
        with patch("agents.backup.restore_verifier.BackblazeConnector"):
            result = verifier.verify()
        assert result["success"] is False
        assert result["reason"] == "no_recent_backups"

    def test_successful_restore_logs_verified_true(self):
        db = MagicMock()
        db.get_recent_backups.return_value = [
            {"file_path": "backups/postgres/daily/2026-06-12_vance.sql.gz.enc"}
        ]
        with (
            patch("agents.backup.restore_verifier.BackblazeConnector") as MockB2,
            patch("agents.backup.restore_verifier.BackupEncryptor") as MockEnc,
            patch("agents.backup.restore_verifier.get_db") as mock_get_db,
            patch("agents.backup.restore_verifier.subprocess.run"),
        ):
            MockB2.return_value.download_file.return_value = {"data": b"encrypted"}
            MockEnc.return_value.decrypt.return_value = b"dump_data"
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.__enter__ = lambda s: mock_cur
            mock_cur.__exit__ = MagicMock(return_value=False)
            mock_cur.fetchone.return_value = (5,)
            mock_conn.__enter__ = lambda s: mock_conn
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.cursor.return_value = mock_cur
            mock_get_db.return_value = mock_conn
            verifier = self._verifier(db)
            result = verifier.verify()
        assert result["success"] is True
        db.insert_log.assert_called_once()
        assert db.insert_log.call_args[1]["verified"] is True

    def test_verification_failure_alerts_security_and_reporting(self):
        db = MagicMock()
        db.get_recent_backups.return_value = [
            {"file_path": "backups/postgres/daily/2026-06-12_vance.sql.gz.enc"}
        ]
        with (
            patch("agents.backup.restore_verifier.BackblazeConnector") as MockB2,
            patch("agents.backup.restore_verifier.BackupEncryptor") as MockEnc,
            patch("agents.backup.restore_verifier.TaskQueue") as MockQueue,
        ):
            MockB2.return_value.download_file.return_value = {"data": b"enc"}
            MockEnc.return_value.decrypt.side_effect = Exception("decrypt failed")
            verifier = self._verifier(db)
            result = verifier.verify()
        assert result["success"] is False
        assert MockQueue.return_value.push.call_count == 2
        agents_notified = {c[1]["agent"] for c in MockQueue.return_value.push.call_args_list}
        assert agents_notified == {"security", "reporting"}

    def test_security_gets_priority_1_alert(self):
        db = MagicMock()
        db.get_recent_backups.return_value = [
            {"file_path": "backups/postgres/daily/key.enc"}
        ]
        with (
            patch("agents.backup.restore_verifier.BackblazeConnector") as MockB2,
            patch("agents.backup.restore_verifier.BackupEncryptor") as MockEnc,
            patch("agents.backup.restore_verifier.TaskQueue") as MockQueue,
        ):
            MockB2.return_value.download_file.return_value = {"data": b"enc"}
            MockEnc.return_value.decrypt.side_effect = Exception("corrupt")
            verifier = self._verifier(db)
            verifier.verify()
        security_calls = [
            c for c in MockQueue.return_value.push.call_args_list
            if c[1]["agent"] == "security"
        ]
        assert security_calls[0][1]["priority"] == 1

    def test_random_backup_selected_from_recent_7_days(self):
        db = MagicMock()
        backup_entries = [
            {"file_path": f"backups/postgres/daily/2026-06-0{i}_vance.sql.gz.enc"}
            for i in range(1, 8)
        ]
        db.get_recent_backups.return_value = backup_entries
        selected_keys = set()
        with (
            patch("agents.backup.restore_verifier.BackblazeConnector") as MockB2,
            patch("agents.backup.restore_verifier.BackupEncryptor") as MockEnc,
            patch("agents.backup.restore_verifier.get_db") as mock_get_db,
            patch("agents.backup.restore_verifier.subprocess.run"),
        ):
            MockB2.return_value.download_file.return_value = {"data": b"enc"}
            MockEnc.return_value.decrypt.return_value = b"dump"
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.__enter__ = lambda s: mock_cur
            mock_cur.__exit__ = MagicMock(return_value=False)
            mock_cur.fetchone.return_value = (1,)
            mock_conn.__enter__ = lambda s: mock_conn
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.cursor.return_value = mock_cur
            mock_get_db.return_value = mock_conn
            verifier = self._verifier(db)
            for _ in range(20):
                result = verifier.verify()
                selected_keys.add(result["backup_key"])
        # With 7 options and 20 trials, statistical chance of hitting >1 is very high
        assert len(selected_keys) > 1

    def test_no_recent_backups_logs_to_db(self):
        db = MagicMock()
        db.get_recent_backups.return_value = []
        verifier = self._verifier(db)
        with patch("agents.backup.restore_verifier.BackblazeConnector"):
            verifier.verify()
        db.insert_log.assert_called_once()
        assert db.insert_log.call_args[1]["backup_type"] == "restore_verify"


# ---------------------------------------------------------------------------
# MailcowBackup
# ---------------------------------------------------------------------------

class TestMailcowBackup:
    def _backup(self, db=None):
        from agents.backup.mailcow_backup import MailcowBackup
        return MailcowBackup(_CFG, db or MagicMock())

    def test_successful_backup_uploads_weekly_key(self):
        db = MagicMock()
        with (
            patch("agents.backup.mailcow_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.mailcow_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.mailcow_backup.httpx.get") as mock_get,
        ):
            MockEnc.return_value.encrypt.return_value = b"enc"
            mock_get.return_value.json.return_value = []
            mock_get.return_value.raise_for_status = MagicMock()
            backup = self._backup(db)
            result = backup.run()
        assert "backups/mailcow" in result["key"]
        assert "W" in result["key"]  # ISO week notation

    def test_exports_domains_mailboxes_and_aliases(self):
        db = MagicMock()
        with (
            patch("agents.backup.mailcow_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.mailcow_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.mailcow_backup.httpx.get") as mock_get,
        ):
            MockEnc.return_value.encrypt.side_effect = lambda data: data  # passthrough
            domain_resp = MagicMock()
            domain_resp.json.return_value = [{"domain": "example.com"}]
            domain_resp.raise_for_status = MagicMock()

            mailbox_resp = MagicMock()
            mailbox_resp.json.return_value = [{"local_part": "admin"}]
            mailbox_resp.raise_for_status = MagicMock()

            alias_resp = MagicMock()
            alias_resp.json.return_value = []
            alias_resp.raise_for_status = MagicMock()

            mock_get.side_effect = [domain_resp, mailbox_resp, alias_resp]
            backup = self._backup(db)
            result = backup.run()
        assert result["domain_count"] == 1
        assert result["mailbox_count"] == 1

    def test_api_error_logs_and_raises(self):
        db = MagicMock()
        with (
            patch("agents.backup.mailcow_backup.BackblazeConnector"),
            patch("agents.backup.mailcow_backup.BackupEncryptor"),
            patch("agents.backup.mailcow_backup.httpx.get") as mock_get,
        ):
            mock_get.side_effect = Exception("connection refused")
            backup = self._backup(db)
            with pytest.raises(Exception, match="connection refused"):
                backup.run()
        db.insert_log.assert_called_once()
        assert db.insert_log.call_args[1]["error"] == "connection refused"

    def test_backup_logged_to_db_on_success(self):
        db = MagicMock()
        with (
            patch("agents.backup.mailcow_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.mailcow_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.mailcow_backup.httpx.get") as mock_get,
        ):
            MockEnc.return_value.encrypt.return_value = b"encrypted_config"
            mock_get.return_value.json.return_value = []
            mock_get.return_value.raise_for_status = MagicMock()
            backup = self._backup(db)
            backup.run()
        db.insert_log.assert_called_once()
        log_kwargs = db.insert_log.call_args[1]
        assert log_kwargs["backup_type"] == "mailcow"
        assert log_kwargs["size_bytes"] == len(b"encrypted_config")

    def test_size_bytes_reflects_encrypted_size(self):
        db = MagicMock()
        with (
            patch("agents.backup.mailcow_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.mailcow_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.mailcow_backup.httpx.get") as mock_get,
        ):
            MockEnc.return_value.encrypt.return_value = b"X" * 2048
            mock_get.return_value.json.return_value = []
            mock_get.return_value.raise_for_status = MagicMock()
            backup = self._backup(db)
            result = backup.run()
        assert result["size_bytes"] == 2048

    def test_uses_api_key_in_header(self):
        db = MagicMock()
        with (
            patch("agents.backup.mailcow_backup.BackblazeConnector") as MockB2,
            patch("agents.backup.mailcow_backup.BackupEncryptor") as MockEnc,
            patch("agents.backup.mailcow_backup.httpx.get") as mock_get,
        ):
            MockEnc.return_value.encrypt.return_value = b"enc"
            mock_get.return_value.json.return_value = []
            mock_get.return_value.raise_for_status = MagicMock()
            backup = self._backup(db)
            backup.run()
        first_call_kwargs = mock_get.call_args_list[0][1]
        assert first_call_kwargs["headers"]["X-API-Key"] == "test-api-key"


# ---------------------------------------------------------------------------
# BackupDB
# ---------------------------------------------------------------------------

class TestBackupDB:
    def _db(self):
        from agents.backup.db import BackupDB
        return BackupDB()

    def _mock_conn(self, fetchone_return=None, fetchall_return=None):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        if fetchone_return is not None:
            mock_cur.fetchone.return_value = fetchone_return
        if fetchall_return is not None:
            mock_cur.fetchall.return_value = fetchall_return
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        return mock_conn, mock_cur

    def test_insert_log_returns_id(self):
        db = self._db()
        mock_conn, mock_cur = self._mock_conn(fetchone_return=(str(uuid.uuid4()),))
        with patch("agents.backup.db.get_db", return_value=mock_conn):
            record_id = db.insert_log(
                backup_type="postgres",
                file_path="backups/postgres/daily/2026-06-12_vance.sql.gz.enc",
                size_bytes=1024,
                duration_seconds=5.0,
            )
        assert record_id is not None

    def test_get_last_backup_returns_none_when_empty(self):
        db = self._db()
        # RealDictCursor path: fetchone returns None → get_last_backup returns None
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = None
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        with patch("agents.backup.db.get_db", return_value=mock_conn):
            result = db.get_last_backup("postgres")
        assert result is None

    def test_get_recent_backups_returns_list(self):
        db = self._db()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: mock_cur
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = []
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        with patch("agents.backup.db.get_db", return_value=mock_conn):
            result = db.get_recent_backups("postgres", days=7)
        assert isinstance(result, list)

    def test_get_last_successful_timestamp_returns_none_when_empty(self):
        db = self._db()
        mock_conn, mock_cur = self._mock_conn(fetchone_return=(None,))
        with patch("agents.backup.db.get_db", return_value=mock_conn):
            result = db.get_last_successful_timestamp()
        assert result is None

    def test_get_last_successful_timestamp_returns_aware_datetime(self):
        db = self._db()
        naive_dt = datetime(2026, 6, 12, 3, 0, 0)
        mock_conn, mock_cur = self._mock_conn(fetchone_return=(naive_dt,))
        with patch("agents.backup.db.get_db", return_value=mock_conn):
            result = db.get_last_successful_timestamp()
        assert result is not None
        assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------

class TestCeleryTasks:
    def test_daily_postgres_backup_task_registered(self):
        import agents.backup.tasks as tasks_mod
        assert hasattr(tasks_mod, "daily_postgres_backup")

    def test_daily_file_backup_task_registered(self):
        import agents.backup.tasks as tasks_mod
        assert hasattr(tasks_mod, "daily_file_backup")

    def test_weekly_restore_verify_task_registered(self):
        import agents.backup.tasks as tasks_mod
        assert hasattr(tasks_mod, "weekly_restore_verify")

    def test_weekly_mailcow_backup_task_registered(self):
        import agents.backup.tasks as tasks_mod
        assert hasattr(tasks_mod, "weekly_mailcow_backup")

    def test_task_helper_builds_backup_task(self):
        import agents.backup.tasks as tasks_mod
        from shared.types import AgentCapability
        t = tasks_mod._task("backup_postgres")
        assert t.agent == AgentCapability.BACKUP
        assert t.payload["action"] == "backup_postgres"

    def test_agent_factory_returns_backup_agent(self):
        import agents.backup.tasks as tasks_mod
        from agents.backup.main import BackupAgent
        with (
            patch("agents._base.config.AgentConfig.load") as mock_load,
            patch("agents.backup.main.BackupDB"),
            patch("agents.backup.main.PostgresBackup"),
            patch("agents.backup.main.FileBackup"),
            patch("agents.backup.main.MailcowBackup"),
            patch("agents.backup.main.RestoreVerifier"),
            patch("agents._base.agent.redis.Redis"),
        ):
            cfg = MagicMock()
            cfg.custom = {}
            mock_load.return_value = cfg
            agent = tasks_mod._agent()
        assert isinstance(agent, BackupAgent)


# ---------------------------------------------------------------------------
# AgentCapability enum
# ---------------------------------------------------------------------------

class TestAgentCapabilityEnum:
    def test_backup_capability_exists(self):
        from shared.types import AgentCapability
        assert AgentCapability.BACKUP == "backup"

    def test_backup_used_in_task(self):
        from shared.types import AgentCapability, Task
        t = Task(
            id="test-id",
            agent=AgentCapability.BACKUP,
            payload={"action": "backup_postgres"},
        )
        assert t.agent == AgentCapability.BACKUP
