"""SSL certificate monitor — expiry tracking, alerts, certbot auto-renew."""

from __future__ import annotations

import socket
import ssl
import subprocess
from datetime import datetime, timezone
from typing import Any

from shared.logger import get_logger

from .db import SecurityDB

logger = get_logger(__name__)

ALERT_THRESHOLDS_DAYS = [30, 7, 1]


class SSLMonitor:

    def __init__(self, db: SecurityDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._domains: list[str] = cfg.get("ssl_domains", [])
        self._auto_renew_domains: set[str] = set(cfg.get("auto_renew_domains", []))

    # ------------------------------------------------------------------

    def check_all(self) -> dict[str, Any]:
        """Check all configured domains. Return per-domain results."""
        results: dict[str, Any] = {}
        expiring: list[str] = []

        for domain in self._domains:
            result = self.check_domain(domain)
            results[domain] = result
            if result.get("days_remaining") is not None:
                days = result["days_remaining"]
                if any(days <= t for t in ALERT_THRESHOLDS_DAYS):
                    expiring.append(domain)
                    if domain in self._auto_renew_domains:
                        renewed = self.auto_renew(domain)
                        result["renewal_attempted"] = True
                        result["renewal_success"] = renewed

        return {"domains": results, "expiring": expiring}

    def check_domain(self, domain: str) -> dict[str, Any]:
        """Connect via TLS and read certificate expiry. Upserts ssl_certs row."""
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((domain, 443), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                    cert = ssock.getpeercert()

            not_after_str = cert.get("notAfter", "")
            expires_at = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(
                tzinfo=timezone.utc
            )
            days_remaining = (expires_at - datetime.now(timezone.utc)).days

            issuer = dict(x[0] for x in cert.get("issuer", [])).get("organizationName", "")
            self._db.upsert_ssl_cert(
                domain=domain,
                expires_at=expires_at,
                auto_renew=domain in self._auto_renew_domains,
                issuer=issuer,
            )

            return {
                "domain": domain,
                "ok": True,
                "expires_at": expires_at.isoformat(),
                "days_remaining": days_remaining,
                "issuer": issuer,
            }

        except Exception as exc:
            self._db.upsert_ssl_cert(domain=domain, expires_at=None, error=str(exc))
            logger.warning("ssl_check_failed", domain=domain, error=str(exc))
            return {"domain": domain, "ok": False, "error": str(exc), "days_remaining": None}

    def auto_renew(self, domain: str) -> bool:
        """Run certbot renew for the domain. Returns True if successful."""
        try:
            result = subprocess.run(
                ["certbot", "renew", "--cert-name", domain, "--non-interactive", "--quiet"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                logger.info("certbot_renewal_success", domain=domain)
                return True
            logger.error("certbot_renewal_failed", domain=domain, stderr=result.stderr)
            return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.error("certbot_not_available", domain=domain, error=str(exc))
            return False
