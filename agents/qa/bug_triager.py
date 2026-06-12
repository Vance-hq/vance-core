"""
Bug triager — classifies bug severity and routes to the right response.

P0 (production down)    → enqueue hotfix to dev immediately
P1 (major feature down) → enqueue fix_bug to dev
P2 / P3                 → create GitHub issue, add to backlog
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from shared.llm.client import llm
from shared.logger import get_logger

from .db import QaDB

logger = get_logger(__name__)

_GITHUB_API = "https://api.github.com"

_TRIAGE_SYSTEM = """You are a senior software engineer performing bug triage.

Given an error log, stack trace, affected user count, and product, classify the bug.

Output a JSON object:
  severity           (string) — P0 | P1 | P2 | P3
    P0 = production down / complete outage
    P1 = major feature broken, no workaround
    P2 = feature degraded or slow, workaround exists
    P3 = minor / cosmetic
  likely_cause       (string) — one sentence root cause hypothesis
  affected_component (string) — e.g. "backend/api", "frontend/dashboard"

Return only valid JSON — no explanation.
"""

_SEVERITY_LABELS = {"P0": "critical", "P1": "high", "P2": "medium", "P3": "low"}
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def enqueue_hotfix(
    repo: str,
    description: str,
    error_context: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="dev",
            payload={
                "action": "hotfix",
                "repo": repo,
                "description": description,
                "error_context": error_context,
            },
            priority=1,
        )
    except Exception as exc:
        logger.warning("hotfix_enqueue_failed", error=str(exc))


def enqueue_fix_bug(
    repo: str,
    description: str,
    error_context: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="dev",
            payload={
                "action": "fix_bug",
                "repo": repo,
                "issue_number": 0,
                "issue_body": description,
                "error_logs": error_context,
            },
            priority=2,
        )
    except Exception as exc:
        logger.warning("fix_bug_enqueue_failed", error=str(exc))


class BugTriager:

    def __init__(self, db: QaDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._github_token = cfg.get("github_token", "")
        self._github_org = cfg.get("github_org", "")

    def triage(
        self,
        product: str,
        error_log: str,
        stack_trace: str,
        affected_users_count: int,
    ) -> dict[str, Any]:
        raw = llm.complete(
            messages=[{
                "role": "user",
                "content": (
                    f"Product: {product}\n"
                    f"Affected users: {affected_users_count}\n\n"
                    f"Error log:\n{error_log}\n\n"
                    f"Stack trace:\n{stack_trace or 'Not provided'}"
                ),
            }],
            system=_TRIAGE_SYSTEM,
            max_tokens=300,
            metadata={"caller": "qa.bug_triager"},
        ).content[0].text.strip()

        try:
            match = _JSON_RE.search(raw)
            analysis = json.loads(match.group() if match else raw)
        except (json.JSONDecodeError, AttributeError):
            analysis = {"severity": "P2", "likely_cause": "Unknown", "affected_component": "unknown"}

        severity = analysis.get("severity", "P2")
        likely_cause = analysis.get("likely_cause", "")
        affected_component = analysis.get("affected_component", "")

        # Save to DB
        bug_id = self._db.save_bug(
            product=product,
            severity=severity,
            title=f"[{severity}] {likely_cause[:120]}",
            stack_trace=stack_trace[:1000] if stack_trace else "",
            affected_users=affected_users_count,
        )

        prod_cfg = self._cfg.get("products", {}).get(product, {})
        repo = prod_cfg.get("repo", "vance-app")
        description = f"[{severity}] {likely_cause}: {error_log[:200]}"

        github_issue = None

        if severity == "P0":
            enqueue_hotfix(
                repo=repo,
                description=description,
                error_context=stack_trace or error_log,
            )
            logger.error("p0_bug_hotfix_enqueued", product=product, cause=likely_cause)

        elif severity == "P1":
            enqueue_fix_bug(
                repo=repo,
                description=description,
                error_context=stack_trace or error_log,
            )
            logger.warning("p1_bug_fix_enqueued", product=product, cause=likely_cause)

        else:
            # P2 / P3 → GitHub issue
            github_issue = self._create_github_issue(
                repo=repo,
                severity=severity,
                product=product,
                title=f"[{severity}] {likely_cause[:80]}",
                body=(
                    f"**Severity:** {severity}\n"
                    f"**Product:** {product}\n"
                    f"**Affected users:** {affected_users_count}\n"
                    f"**Likely cause:** {likely_cause}\n"
                    f"**Affected component:** {affected_component}\n\n"
                    f"**Error log:**\n```\n{error_log[:500]}\n```\n\n"
                    f"**Stack trace:**\n```\n{(stack_trace or 'N/A')[:500]}\n```"
                ),
            )
            logger.info(
                "bug_issue_created",
                product=product,
                severity=severity,
                issue=github_issue,
            )

        return {
            "bug_id": bug_id,
            "severity": severity,
            "likely_cause": likely_cause,
            "affected_component": affected_component,
            "github_issue": github_issue,
        }

    # ------------------------------------------------------------------

    def _create_github_issue(
        self,
        repo: str,
        severity: str,
        product: str,
        title: str,
        body: str,
    ) -> int | None:
        label = _SEVERITY_LABELS.get(severity, "low")
        try:
            resp = httpx.post(
                f"{_GITHUB_API}/repos/{self._github_org}/{repo}/issues",
                headers={
                    "Authorization": f"Bearer {self._github_token}",
                    "Accept": "application/vnd.github+json",
                },
                json={
                    "title": title,
                    "body": body,
                    "labels": ["bug", label, f"product:{product}"],
                },
                timeout=15,
            )
            if resp.status_code == 201:
                return resp.json().get("number")
        except Exception as exc:
            logger.warning("github_issue_create_failed", repo=repo, error=str(exc))
        return None
