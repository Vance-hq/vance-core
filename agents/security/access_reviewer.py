"""Access reviewer — periodic audit of GitHub, Supabase, Vercel, Cloudflare access."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from shared.logger import get_logger

from .db import SecurityDB

logger = get_logger(__name__)

STALE_KEY_DAYS = 90


class AccessReviewer:

    def __init__(self, db: SecurityDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._services: list[str] = cfg.get("access_review_services", ["github", "cloudflare"])

    # ------------------------------------------------------------------

    def review_all(self) -> dict[str, Any]:
        """Review access across all configured services. Saves findings to DB."""
        all_flagged: list[dict[str, Any]] = []
        per_service: dict[str, Any] = {}

        for service in self._services:
            findings = self.review_service(service)
            per_service[service] = findings
            flagged = self.flag_stale_keys(findings)
            all_flagged.extend(flagged)

        return {"flagged": all_flagged, "per_service": per_service, "total_flagged": len(all_flagged)}

    def review_service(self, service: str) -> list[dict[str, Any]]:
        """Pull current access list for a service. Returns account dicts."""
        try:
            dispatch = {
                "github": self._review_github,
                "cloudflare": self._review_cloudflare,
                "vercel": self._review_vercel,
            }
            fn = dispatch.get(service)
            if not fn:
                logger.warning("unknown_review_service", service=service)
                return []
            return fn()
        except Exception as exc:
            logger.error("access_review_failed", service=service, error=str(exc))
            return []

    def flag_stale_keys(
        self,
        accounts: list[dict[str, Any]],
        days: int = STALE_KEY_DAYS,
    ) -> list[dict[str, Any]]:
        """Flag accounts with last_used older than `days` days. Saves to DB."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        flagged: list[dict[str, Any]] = []

        for account in accounts:
            last_used = account.get("last_used")
            if isinstance(last_used, str):
                try:
                    last_used = datetime.fromisoformat(last_used.replace("Z", "+00:00"))
                except ValueError:
                    last_used = None

            is_stale = last_used is not None and last_used < cutoff
            is_unknown = last_used is None and account.get("flag_if_no_usage", False)
            should_flag = is_stale or is_unknown

            self._db.save_access_audit(
                service=account.get("service", "unknown"),
                account=account.get("account", ""),
                access_level=account.get("access_level", ""),
                last_used=last_used,
                flagged=should_flag,
                flag_reason="stale_key" if should_flag else None,
            )

            if should_flag:
                flagged.append({**account, "flag_reason": "stale_key"})

        return flagged

    # ------------------------------------------------------------------
    # Per-service collectors
    # ------------------------------------------------------------------

    def _review_github(self) -> list[dict[str, Any]]:
        from agents.integrations.connectors.github import GitHubConnector

        gh = GitHubConnector(called_by="security", method_name="list_collaborators")
        collaborators = gh.list_collaborators()
        return [
            {
                "service": "github",
                "account": c.get("login", ""),
                "access_level": c.get("role_name", ""),
                "last_used": None,
            }
            for c in collaborators
        ]

    def _review_cloudflare(self) -> list[dict[str, Any]]:
        from agents.integrations.connectors.cloudflare import CloudflareConnector

        cf = CloudflareConnector(called_by="security", method_name="list_members")
        members = cf.list_account_members()
        return [
            {
                "service": "cloudflare",
                "account": m.get("user", {}).get("email", ""),
                "access_level": ", ".join(
                    r.get("name", "") for r in m.get("roles", [])
                ),
                "last_used": None,
                "flag_if_no_usage": False,
            }
            for m in members
        ]

    def _review_vercel(self) -> list[dict[str, Any]]:
        from agents.integrations.connectors.vercel import VercelConnector

        vc = VercelConnector(called_by="security", method_name="list_members")
        members = vc.list_team_members()
        return [
            {
                "service": "vercel",
                "account": m.get("email", m.get("username", "")),
                "access_level": m.get("role", ""),
                "last_used": m.get("confirmed", None),
            }
            for m in members
        ]
