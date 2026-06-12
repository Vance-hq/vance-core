"""
Dependency updater — finds and applies safe package updates.

- Minor/patch updates applied automatically + tests run.
- Major version bumps flagged in result, NOT auto-applied.
- Opens a PR after applying minor/patch updates.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import Any

import httpx

from shared.logger import get_logger

from .db import DevDB

logger = get_logger(__name__)

_GITHUB_API = "https://api.github.com"


def _semver_is_major_bump(current: str, latest: str) -> bool:
    """Return True if latest is a major version bump over current."""
    try:
        cur_major = int(current.lstrip("^~").split(".")[0])
        lat_major = int(latest.lstrip("^~").split(".")[0])
        return lat_major > cur_major
    except (ValueError, IndexError):
        return False


class DependencyUpdater:

    def __init__(self, db: DevDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._repos_path = cfg.get("repos_path", "/repos")
        self._github_token = cfg.get("github_token", "")
        self._github_org = cfg.get("github_org", "")
        self._timeout = int(cfg.get("subprocess_timeout_s", 300))

    def update(self, repo: str) -> dict[str, Any]:
        start = time.time()
        repo_path = os.path.join(self._repos_path, repo)
        repo_cfg = self._cfg.get("repos", {}).get(repo, {})
        repo_type = repo_cfg.get("type", "python")

        outdated = self._get_outdated(repo_path, repo_type)
        minor_patch = []
        major_updates = []

        for pkg, info in outdated.items():
            current = info.get("current") or info.get("version", "0.0.0")
            latest = info.get("latest") or info.get("latest_version", current)
            if _semver_is_major_bump(current, latest):
                major_updates.append({"package": pkg, "current": current, "latest": latest})
            else:
                minor_patch.append({"package": pkg, "current": current, "latest": latest})

        updated_count = 0
        if minor_patch:
            self._apply_updates(repo_path, repo_type, [p["package"] for p in minor_patch])
            test_result = self._run_tests(repo_path, repo_type)

            if test_result.returncode == 0:
                packages_str = ", ".join(p["package"] for p in minor_patch[:5])
                branch = f"deps/update-{int(start)}"
                default_branch = repo_cfg.get("default_branch", "main")
                self._git_commit_push(
                    repo_path,
                    branch=branch,
                    message=f"chore(deps): update {packages_str}",
                    default_branch=default_branch,
                )
                self._open_pr(
                    repo=repo,
                    title=f"chore(deps): update {len(minor_patch)} package(s)",
                    body=self._pr_body(minor_patch, major_updates),
                    head=branch,
                    base=default_branch,
                )
                updated_count = len(minor_patch)

        duration = time.time() - start
        self._db.save_build_log(
            repo=repo,
            task_type="dependency_update",
            success=True,
            duration_seconds=duration,
        )

        return {
            "repo": repo,
            "updated": updated_count,
            "major_updates_pending": len(major_updates),
            "major_updates": major_updates,
        }

    # ------------------------------------------------------------------

    def _get_outdated(self, repo_path: str, repo_type: str) -> dict[str, Any]:
        if repo_type == "node":
            result = subprocess.run(
                ["npm", "outdated", "--json"],
                capture_output=True, text=True, cwd=repo_path, timeout=self._timeout,
            )
            raw = result.stdout.strip()
        else:
            result = subprocess.run(
                ["pip", "list", "--outdated", "--format=json"],
                capture_output=True, text=True, cwd=repo_path, timeout=self._timeout,
            )
            raw = result.stdout.strip()

        if not raw:
            return {}

        try:
            data = json.loads(raw)
            if isinstance(data, list):
                # pip format: [{name, version, latest_version}, ...]
                return {item["name"]: item for item in data}
            return data  # npm format: {pkg: {current, wanted, latest}}
        except (json.JSONDecodeError, KeyError):
            return {}

    def _apply_updates(
        self,
        repo_path: str,
        repo_type: str,
        packages: list[str],
    ) -> None:
        if repo_type == "node":
            subprocess.run(
                ["npm", "install"] + packages,
                capture_output=True, cwd=repo_path, timeout=self._timeout,
            )
        else:
            subprocess.run(
                ["pip", "install", "--upgrade"] + packages,
                capture_output=True, cwd=repo_path, timeout=self._timeout,
            )

    def _run_tests(self, repo_path: str, repo_type: str) -> subprocess.CompletedProcess:
        cmd = ["npm", "test", "--", "--ci"] if repo_type == "node" else ["pytest", "-x", "-q"]
        return subprocess.run(
            cmd, capture_output=True, text=True, cwd=repo_path, timeout=self._timeout,
        )

    def _git_commit_push(
        self,
        repo_path: str,
        branch: str,
        message: str,
        default_branch: str,
    ) -> None:
        subprocess.run(["git", "checkout", "-b", branch], capture_output=True, cwd=repo_path)
        subprocess.run(["git", "add", "-A"], capture_output=True, cwd=repo_path)
        subprocess.run(["git", "commit", "-m", message], capture_output=True, cwd=repo_path)
        subprocess.run(
            ["git", "push", "--set-upstream", "origin", branch],
            capture_output=True, cwd=repo_path,
        )

    def _open_pr(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> dict[str, Any]:
        try:
            resp = httpx.post(
                f"{_GITHUB_API}/repos/{self._github_org}/{repo}/pulls",
                headers={
                    "Authorization": f"Bearer {self._github_token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"title": title, "body": body, "head": head, "base": base},
                timeout=15,
            )
            if resp.status_code in (200, 201):
                return resp.json()
        except Exception as exc:
            logger.warning("dep_update_open_pr_failed", repo=repo, error=str(exc))
        return {}

    def _pr_body(
        self,
        minor_patch: list[dict],
        major_pending: list[dict],
    ) -> str:
        lines = ["## Dependency Updates\n\n### Applied (minor/patch)\n"]
        for p in minor_patch:
            lines.append(f"- `{p['package']}`: {p['current']} → {p['latest']}")
        if major_pending:
            lines.append("\n### Major Updates Pending (manual review)\n")
            for p in major_pending:
                lines.append(f"- `{p['package']}`: {p['current']} → {p['latest']} ⚠️ breaking changes likely")
        return "\n".join(lines)
