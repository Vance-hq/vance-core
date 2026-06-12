"""
Environment syncer — keeps staging DB schema in sync with production.

Weekly task:
  1. pg_dump --schema-only from production
  2. Apply schema diff to staging (non-destructive)
  3. Run seed script to populate staging with test data
"""

from __future__ import annotations

import subprocess
from typing import Any

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)


class EnvSyncer:

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg
        self._timeout = int(cfg.get("subprocess_timeout_s", 300))
        self._prod_db_url = cfg.get("prod_db_url", settings.DATABASE_URL)
        self._staging_db_url = cfg.get("staging_db_url", "")

    # ------------------------------------------------------------------

    def sync(self, repo: str) -> dict[str, Any]:
        """Full schema sync + seed for a given repo's staging environment."""
        if not self._staging_db_url:
            return {"success": False, "reason": "staging_db_url not configured"}

        schema_ok = self._sync_schema()
        seed_ok = self._run_seed(repo)

        return {
            "success": schema_ok and seed_ok,
            "repo": repo,
            "schema_synced": schema_ok,
            "seed_run": seed_ok,
        }

    def _sync_schema(self) -> bool:
        """Dump production schema and apply to staging (schema only, no data)."""
        try:
            dump = subprocess.run(
                ["pg_dump", "--schema-only", "--no-owner", "--no-privileges", self._prod_db_url],
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            if dump.returncode != 0:
                logger.error("pg_dump_failed", stderr=dump.stderr[:500])
                return False

            apply = subprocess.run(
                ["psql", "--quiet", self._staging_db_url],
                input=dump.stdout,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            if apply.returncode != 0:
                logger.error("schema_apply_failed", stderr=apply.stderr[:500])
                return False

            logger.info("schema_sync_complete")
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.error("schema_sync_error", error=str(exc))
            return False

    def _run_seed(self, repo: str) -> bool:
        """Run the seed script for the given repo."""
        import os

        repo_cfg = self._cfg.get("repos", {}).get(repo, {})
        seed_cmd = repo_cfg.get("seed_cmd")

        if not seed_cmd:
            logger.info("no_seed_cmd_configured", repo=repo)
            return True

        repos_path = self._cfg.get("repos_path", "/repos")
        repo_path = os.path.join(repos_path, repo)

        try:
            result = subprocess.run(
                seed_cmd if isinstance(seed_cmd, list) else seed_cmd.split(),
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=self._timeout,
                env={**__import__("os").environ, "DATABASE_URL": self._staging_db_url},
            )
            if result.returncode != 0:
                logger.error("seed_failed", repo=repo, stderr=result.stderr[:500])
                return False

            logger.info("seed_complete", repo=repo)
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.error("seed_error", repo=repo, error=str(exc))
            return False
