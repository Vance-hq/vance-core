"""Weekly Mailcow configuration backup — export domain/mailbox config via API."""

from __future__ import annotations

import json
import time
from datetime import date

import httpx

from agents.integrations.connectors.backblaze import BackblazeConnector
from shared.config.settings import settings
from shared.logger import get_logger

from .db import BackupDB
from .encryptor import BackupEncryptor

logger = get_logger(__name__)

_PREFIX = "backups/mailcow"
_TIMEOUT = 30


class MailcowBackup:
    """
    Export Mailcow domain and mailbox configuration and store encrypted backup.

    Losing Mailcow config means losing all sender warm-up history.
    """

    def __init__(self, cfg: dict, db: BackupDB | None = None) -> None:
        self._cfg = cfg
        self._db = db or BackupDB()
        self._storage = BackblazeConnector()
        key = cfg.get("encryption_key") or getattr(settings, "BACKUP_ENCRYPTION_KEY", "")
        self._enc = BackupEncryptor(key)
        host = cfg.get("mailcow_host") or getattr(settings, "MAILCOW_HOST", "")
        api_key = cfg.get("mailcow_api_key") or getattr(settings, "MAILCOW_API_KEY", "")
        self._base_url = f"https://{host}/api/v1"
        self._headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict:
        t0 = time.monotonic()
        today = date.today()

        try:
            config = self._export_config()
        except Exception as exc:
            self._db.insert_log(
                backup_type="mailcow",
                file_path="",
                size_bytes=0,
                duration_seconds=round(time.monotonic() - t0, 2),
                error=str(exc),
            )
            raise

        raw_bytes = json.dumps(config, indent=2).encode()
        encrypted = self._enc.encrypt(raw_bytes)
        size_bytes = len(encrypted)

        iso_week = today.isocalendar()
        key = f"{_PREFIX}/{iso_week.year}-W{iso_week.week:02d}_mailcow.json.enc"
        self._storage.upload_file(encrypted, key, "application/octet-stream")

        duration = round(time.monotonic() - t0, 2)
        self._db.insert_log(
            backup_type="mailcow",
            file_path=key,
            size_bytes=size_bytes,
            duration_seconds=duration,
        )

        return {
            "key": key,
            "size_bytes": size_bytes,
            "duration_seconds": duration,
            "domain_count": len(config.get("domains", [])),
            "mailbox_count": len(config.get("mailboxes", [])),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _export_config(self) -> dict:
        domains = self._get("/get/domain/all")
        mailboxes = self._get("/get/mailbox/all")
        aliases = self._get("/get/alias/all")
        return {
            "domains": domains if isinstance(domains, list) else [],
            "mailboxes": mailboxes if isinstance(mailboxes, list) else [],
            "aliases": aliases if isinstance(aliases, list) else [],
        }

    def _get(self, path: str) -> list | dict:
        resp = httpx.get(
            f"{self._base_url}{path}",
            headers=self._headers,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
