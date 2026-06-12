"""
Release notes generator — pulls merged PRs since last release, LLM summarizes
by category, posts to GitHub Releases and surfaces to content agent.
"""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import DeployDB

logger = get_logger(__name__)

_CATEGORIES = ["new_features", "improvements", "bug_fixes", "infrastructure"]

_SUMMARY_PROMPT = """You are writing release notes for a SaaS product.

Categorize these merged pull requests into: new_features, improvements, bug_fixes, infrastructure.

PRs:
{pr_list}

Respond with valid JSON only:
{{
  "new_features": ["item 1", "item 2"],
  "improvements": ["item 1"],
  "bug_fixes": ["item 1"],
  "infrastructure": ["item 1"]
}}

Keep each item to one clear, user-facing sentence. Omit empty categories.
Skip internal/chore PRs that don't affect users."""


def _enqueue_content_agent(repo: str, notes: dict[str, Any], tag: str) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="content",
            payload={
                "action": "user_facing_release",
                "repo": repo,
                "tag": tag,
                "notes": notes,
            },
        )
    except Exception as exc:
        logger.warning("content_enqueue_failed", repo=repo, error=str(exc))


class ReleaseNotesGenerator:

    def __init__(self, db: DeployDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._github_org = cfg.get("github_org", "vance-hq")

    # ------------------------------------------------------------------

    def generate(self, repo: str, tag: str, build_id: str = "") -> dict[str, Any]:
        prs = self._get_merged_prs(repo, since_tag=self._get_previous_tag(repo))
        if not prs:
            logger.info("no_prs_since_last_release", repo=repo, tag=tag)
            return {"repo": repo, "tag": tag, "prs": 0, "notes": {}}

        notes = self._summarize_with_llm(prs)
        markdown = self._format_markdown(tag, notes)

        release = self._post_github_release(repo, tag, markdown)
        _enqueue_content_agent(repo, notes, tag)

        logger.info("release_notes_generated", repo=repo, tag=tag, prs=len(prs))
        return {
            "repo": repo,
            "tag": tag,
            "prs": len(prs),
            "notes": notes,
            "github_release_url": release.get("html_url", ""),
        }

    # ------------------------------------------------------------------

    def _get_merged_prs(self, repo: str, since_tag: str | None) -> list[dict[str, Any]]:
        try:
            from agents.integrations.connectors.github import GitHubConnector

            gh = GitHubConnector(called_by="deploy.release_notes", method_name="list_prs")
            prs = gh.list_prs(repo=repo, state="closed")
            merged = [
                pr for pr in prs
                if pr.get("merged_at") and pr.get("base", {}).get("ref") == "main"
            ]
            return merged[:50]
        except Exception as exc:
            logger.warning("get_merged_prs_failed", repo=repo, error=str(exc))
            return []

    def _get_previous_tag(self, repo: str) -> str | None:
        try:
            from agents.integrations.connectors.github import GitHubConnector

            gh = GitHubConnector(called_by="deploy.release_notes", method_name="list_releases")
            releases = gh.list_releases(repo=repo, limit=2)
            if len(releases) >= 2:
                return releases[1].get("tag_name")
            return None
        except Exception:
            return None

    def _summarize_with_llm(self, prs: list[dict[str, Any]]) -> dict[str, list[str]]:
        pr_list = "\n".join(
            f"- PR #{pr.get('number', '')}: {pr.get('title', '')}"
            for pr in prs
        )
        prompt = _SUMMARY_PROMPT.format(pr_list=pr_list)
        try:
            response = llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system="You write clear, concise release notes for software products.",
                metadata={"caller": "deploy.release_notes"},
            )
            raw = response.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            return {cat: data.get(cat, []) for cat in _CATEGORIES if data.get(cat)}
        except Exception as exc:
            logger.warning("llm_summarize_failed", error=str(exc))
            return {"improvements": [f"{len(prs)} changes merged"]}

    def _format_markdown(self, tag: str, notes: dict[str, list[str]]) -> str:
        sections = []
        label_map = {
            "new_features":  "## ✨ New Features",
            "improvements":  "## 🚀 Improvements",
            "bug_fixes":     "## 🐛 Bug Fixes",
            "infrastructure": "## 🔧 Infrastructure",
        }
        for cat in _CATEGORIES:
            items = notes.get(cat, [])
            if items:
                section = label_map[cat] + "\n" + "\n".join(f"- {item}" for item in items)
                sections.append(section)
        return "\n\n".join(sections) if sections else "No user-facing changes."

    def _post_github_release(self, repo: str, tag: str, body: str) -> dict[str, Any]:
        try:
            from agents.integrations.connectors.github import GitHubConnector

            gh = GitHubConnector(called_by="deploy.release_notes", method_name="create_release")
            return gh.create_release(repo=repo, tag=tag, name=tag, body=body)
        except Exception as exc:
            logger.warning("github_release_post_failed", repo=repo, tag=tag, error=str(exc))
            return {}
