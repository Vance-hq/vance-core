"""
Builder — runs Claude Code as a subprocess to build features, fix bugs, and hotfix production.

Claude Code is invoked as:
  claude -p "<prompt>" --output-format json --dangerously-skip-permissions

Git operations run via subprocess in the cloned repo directory.
GitHub PRs are opened via the REST API directly.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import httpx

from shared.logger import get_logger

from .db import DevDB

logger = get_logger(__name__)

_GITHUB_API = "https://api.github.com"

_BUILD_PROMPT = """You are working in the {repo} codebase.

Build the following feature: {feature_description}

Acceptance criteria:
{acceptance_criteria}

Instructions:
- Follow existing code patterns and conventions you find in this repo.
- Write tests for all new code.
- Do not modify unrelated files.
- Keep changes minimal and focused.
"""

_BUG_PROMPT = """You are working in the {repo} codebase.

Fix the following bug (GitHub issue #{issue_number}):

Issue title: {issue_title}
Issue description: {issue_body}

Error logs:
{error_logs}

Instructions:
- Identify the root cause before changing any code.
- Write or update a failing test that reproduces the bug first.
- Fix the bug with the minimal change necessary.
- Do not modify unrelated code.
"""

_HOTFIX_PROMPT = """HOTFIX — production is affected. You are working in the {repo} codebase.

Problem: {description}

Error context:
{error_context}

Instructions:
- Fix the issue immediately with the smallest safe change.
- Verify the fix doesn't break existing tests.
- Do not refactor or improve anything beyond the minimal fix.
"""


def enqueue_human_review(
    repo: str,
    task_type: str,
    description: str,
    error_context: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="reporting",
            payload={
                "action": "human_review_required",
                "repo": repo,
                "task_type": task_type,
                "description": description,
                "error_context": error_context,
            },
        )
    except Exception as exc:
        logger.warning("human_review_enqueue_failed", repo=repo, error=str(exc))


def enqueue_deploy(repo: str, environment: str = "production") -> None:
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="dev",
            payload={"action": "deploy", "repo": repo, "environment": environment},
            priority=1,
        )
    except Exception as exc:
        logger.warning("deploy_enqueue_failed", repo=repo, error=str(exc))


class Builder:

    def __init__(self, db: DevDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._repos_path = cfg.get("repos_path", "/repos")
        self._github_token = cfg.get("github_token", "")
        self._github_org = cfg.get("github_org", "")
        self._claude_bin = cfg.get("claude_code_bin", "/usr/local/bin/claude")
        self._timeout = int(cfg.get("subprocess_timeout_s", 300))

    # ------------------------------------------------------------------
    # build_feature
    # ------------------------------------------------------------------

    def build_feature(
        self,
        repo: str,
        feature_description: str,
        acceptance_criteria: str,
        target_branch: str,
    ) -> dict[str, Any]:
        start = time.time()
        repo_path = os.path.join(self._repos_path, repo)
        repo_cfg = self._cfg.get("repos", {}).get(repo, {})
        default_branch = repo_cfg.get("default_branch", "main")

        # Prep repo
        self._git_pull(repo_path, default_branch)
        self._git_checkout_branch(repo_path, target_branch)

        prompt = _BUILD_PROMPT.format(
            repo=repo,
            feature_description=feature_description,
            acceptance_criteria=acceptance_criteria,
        )

        for attempt in range(1, 3):
            self._run_claude(repo_path, prompt)
            test_result = self._run_tests(repo_path, repo_cfg.get("type", "python"))

            if test_result.returncode == 0:
                self._git_commit_push(
                    repo_path,
                    branch=target_branch,
                    message=f"feat: {feature_description[:72]}",
                )
                pr = self._open_pr(
                    repo=repo,
                    title=f"feat: {feature_description[:72]}",
                    body=f"## Feature\n{feature_description}\n\n## Acceptance Criteria\n{acceptance_criteria}",
                    head=target_branch,
                    base=default_branch,
                )
                duration = time.time() - start
                self._db.save_build_log(
                    repo=repo, task_type="build_feature",
                    success=True, duration_seconds=duration,
                )
                return {"success": True, "pr_number": pr.get("number"), "pr_url": pr.get("html_url")}

            error_context = test_result.stderr or test_result.stdout
            if attempt == 1:
                # Retry with error context appended
                prompt = prompt + f"\n\nPrevious attempt failed tests:\n{error_context}\nFix the failing tests."

        # Both attempts failed
        duration = time.time() - start
        self._db.save_build_log(
            repo=repo, task_type="build_feature",
            success=False, duration_seconds=duration, error_msg=error_context,
        )
        enqueue_human_review(
            repo=repo,
            task_type="build_feature",
            description=feature_description,
            error_context=error_context,
        )
        return {"success": False, "flagged_for_review": True, "error": error_context}

    # ------------------------------------------------------------------
    # fix_bug
    # ------------------------------------------------------------------

    def fix_bug(
        self,
        repo: str,
        issue_number: int,
        issue_body: str,
        error_logs: str,
    ) -> dict[str, Any]:
        start = time.time()
        repo_path = os.path.join(self._repos_path, repo)
        repo_cfg = self._cfg.get("repos", {}).get(repo, {})
        default_branch = repo_cfg.get("default_branch", "main")

        # Fetch issue from GitHub
        issue = self._fetch_issue(repo, issue_number)
        issue_title = issue.get("title", f"Issue #{issue_number}")
        issue_body_text = issue.get("body", issue_body) or issue_body

        branch = f"fix/issue-{issue_number}"
        self._git_pull(repo_path, default_branch)
        self._git_checkout_branch(repo_path, branch)

        prompt = _BUG_PROMPT.format(
            repo=repo,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_body=issue_body_text,
            error_logs=error_logs or "No error logs provided.",
        )

        for attempt in range(1, 3):
            self._run_claude(repo_path, prompt)
            test_result = self._run_tests(repo_path, repo_cfg.get("type", "python"))

            if test_result.returncode == 0:
                self._git_commit_push(
                    repo_path,
                    branch=branch,
                    message=f"fix: resolve issue #{issue_number} — {issue_title[:60]}",
                )
                pr = self._open_pr(
                    repo=repo,
                    title=f"fix: issue #{issue_number} — {issue_title[:60]}",
                    body=f"Closes #{issue_number}\n\n{issue_body_text[:500]}",
                    head=branch,
                    base=default_branch,
                )
                self._close_issue(repo, issue_number)
                duration = time.time() - start
                self._db.save_build_log(
                    repo=repo, task_type="fix_bug",
                    success=True, duration_seconds=duration, issue_number=issue_number,
                )
                return {
                    "success": True,
                    "pr_number": pr.get("number"),
                    "pr_url": pr.get("html_url"),
                    "issue_closed": True,
                }

            error_context = test_result.stderr or test_result.stdout
            if attempt == 1:
                prompt = prompt + f"\n\nTest failures:\n{error_context}\nFix these failures."

        duration = time.time() - start
        self._db.save_build_log(
            repo=repo, task_type="fix_bug",
            success=False, duration_seconds=duration, issue_number=issue_number,
        )
        return {"success": False, "flagged_for_review": True}

    # ------------------------------------------------------------------
    # hotfix
    # ------------------------------------------------------------------

    def hotfix(
        self,
        repo: str,
        description: str,
        error_context: str,
    ) -> dict[str, Any]:
        start = time.time()
        repo_path = os.path.join(self._repos_path, repo)
        repo_cfg = self._cfg.get("repos", {}).get(repo, {})
        default_branch = repo_cfg.get("default_branch", "main")

        self._git_pull(repo_path, default_branch)

        prompt = _HOTFIX_PROMPT.format(
            repo=repo,
            description=description,
            error_context=error_context or "No additional context.",
        )

        self._run_claude(repo_path, prompt)
        test_result = self._run_tests(repo_path, repo_cfg.get("type", "python"))

        commit_message = f"hotfix: {description[:72]}"
        # Commit directly to default branch — no PR
        self._git_commit_push(repo_path, branch=default_branch, message=commit_message)

        # Trigger deploy immediately
        enqueue_deploy(repo=repo, environment="production")

        # Create post-mortem issue
        postmortem = self._create_postmortem_issue(repo, description, error_context)

        duration = time.time() - start
        self._db.save_build_log(
            repo=repo, task_type="hotfix",
            success=test_result.returncode == 0,
            duration_seconds=duration,
            error_msg=error_context if test_result.returncode != 0 else None,
        )

        return {
            "success": True,
            "branch": default_branch,
            "postmortem_issue": postmortem.get("number"),
            "postmortem_url": postmortem.get("html_url"),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_claude(self, repo_path: str, prompt: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self._claude_bin, "-p", prompt, "--output-format", "json",
             "--dangerously-skip-permissions"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=self._timeout,
        )

    def _run_tests(self, repo_path: str, repo_type: str) -> subprocess.CompletedProcess:
        cmd = ["npm", "test", "--", "--ci"] if repo_type == "node" else ["pytest", "-x", "-q"]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=self._timeout,
        )

    def _git_pull(self, repo_path: str, branch: str) -> None:
        subprocess.run(
            ["git", "pull", "origin", branch],
            capture_output=True, text=True, cwd=repo_path,
        )

    def _git_checkout_branch(self, repo_path: str, branch: str) -> None:
        subprocess.run(
            ["git", "checkout", "-b", branch],
            capture_output=True, text=True, cwd=repo_path,
        )

    def _git_commit_push(self, repo_path: str, branch: str, message: str) -> None:
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
            logger.warning("open_pr_failed", repo=repo, error=str(exc))
        return {}

    def _fetch_issue(self, repo: str, issue_number: int) -> dict[str, Any]:
        try:
            resp = httpx.get(
                f"{_GITHUB_API}/repos/{self._github_org}/{repo}/issues/{issue_number}",
                headers={
                    "Authorization": f"Bearer {self._github_token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.warning("fetch_issue_failed", issue=issue_number, error=str(exc))
        return {}

    def _close_issue(self, repo: str, issue_number: int) -> None:
        try:
            httpx.patch(
                f"{_GITHUB_API}/repos/{self._github_org}/{repo}/issues/{issue_number}",
                headers={
                    "Authorization": f"Bearer {self._github_token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"state": "closed"},
                timeout=15,
            )
        except Exception as exc:
            logger.warning("close_issue_failed", issue=issue_number, error=str(exc))

    def _create_postmortem_issue(
        self,
        repo: str,
        description: str,
        error_context: str,
    ) -> dict[str, Any]:
        try:
            resp = httpx.post(
                f"{_GITHUB_API}/repos/{self._github_org}/{repo}/issues",
                headers={
                    "Authorization": f"Bearer {self._github_token}",
                    "Accept": "application/vnd.github+json",
                },
                json={
                    "title": f"Post-mortem: {description[:80]}",
                    "body": (
                        f"## Hotfix Post-Mortem\n\n"
                        f"**Problem:** {description}\n\n"
                        f"**Error context:**\n```\n{error_context}\n```\n\n"
                        f"## Follow-up\n- [ ] Root cause analysis\n"
                        f"- [ ] Prevention measures\n- [ ] Monitoring improvements"
                    ),
                    "labels": ["post-mortem", "hotfix"],
                },
                timeout=15,
            )
            if resp.status_code == 201:
                return resp.json()
        except Exception as exc:
            logger.warning("postmortem_create_failed", repo=repo, error=str(exc))
        return {}
