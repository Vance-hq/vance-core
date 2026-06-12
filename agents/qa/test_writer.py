"""
Test writer — uses LLM to generate unit, integration, and e2e tests for new features.

Commits generated test files to the feature branch alongside the feature code.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import QaDB

logger = get_logger(__name__)

_WRITE_SYSTEM = """You are a senior QA engineer. Given feature code and acceptance criteria,
generate comprehensive tests.

Output a JSON object with exactly these keys:
  unit_tests        (string) — complete pytest or Jest unit test file content
  integration_test  (string) — integration test file content
  e2e_test          (string) — Playwright TypeScript test file content

The tests must be complete, runnable files. Write meaningful assertions.
Return only valid JSON — no explanation.
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class TestWriter:

    def __init__(self, db: QaDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._repos_path = cfg.get("repos_path", "/repos")
        self._timeout = int(cfg.get("subprocess_timeout_s", 60))

    def write(
        self,
        repo: str,
        feature_code: str,
        acceptance_criteria: str,
        branch: str,
    ) -> dict[str, Any]:
        start = time.time()
        repo_cfg = self._cfg.get("repos", {}).get(repo, {})
        repo_type = repo_cfg.get("type", "python")
        repo_path = os.path.join(self._repos_path, repo)

        raw = llm.complete(
            messages=[{
                "role": "user",
                "content": (
                    f"Repo type: {repo_type}\n"
                    f"Feature code:\n```\n{feature_code}\n```\n\n"
                    f"Acceptance criteria:\n{acceptance_criteria}"
                ),
            }],
            system=_WRITE_SYSTEM,
            max_tokens=3000,
            metadata={"caller": "qa.test_writer"},
        ).content[0].text.strip()

        try:
            match = _JSON_RE.search(raw)
            tests = json.loads(match.group() if match else raw)
        except (json.JSONDecodeError, AttributeError):
            tests = {}

        files_written = []
        unit_written = False
        e2e_written = False
        slug = re.sub(r"[^a-z0-9]+", "_", branch.split("/")[-1].lower())

        if tests.get("unit_tests"):
            ext = "py" if repo_type == "python" else "test.ts"
            unit_path = self._write_test_file(
                repo_path=repo_path,
                subdir="tests/unit" if repo_type == "python" else "src/__tests__",
                filename=f"test_{slug}.{ext}",
                content=tests["unit_tests"],
            )
            files_written.append(unit_path)
            unit_written = True

        if tests.get("integration_test"):
            ext = "py" if repo_type == "python" else "test.ts"
            int_path = self._write_test_file(
                repo_path=repo_path,
                subdir="tests/integration" if repo_type == "python" else "src/__tests__/integration",
                filename=f"test_{slug}_integration.{ext}",
                content=tests["integration_test"],
            )
            files_written.append(int_path)

        if tests.get("e2e_test"):
            e2e_path = self._write_test_file(
                repo_path=repo_path,
                subdir="e2e",
                filename=f"{slug}.spec.ts",
                content=tests["e2e_test"],
            )
            files_written.append(e2e_path)
            e2e_written = True

        if files_written:
            self._git_commit(repo_path, branch, files_written)

        duration_ms = int((time.time() - start) * 1000)
        self._db.save_test_run(
            repo=repo,
            run_type="write_tests",
            passed=len(files_written),
            failed=0,
            coverage_pct=0.0,
            duration_ms=duration_ms,
            triggered_by="dev_agent",
        )

        logger.info("tests_written", repo=repo, branch=branch, files=len(files_written))
        return {
            "repo": repo,
            "branch": branch,
            "unit_tests_written": unit_written,
            "e2e_test_written": e2e_written,
            "files_written": files_written,
        }

    # ------------------------------------------------------------------

    def _write_test_file(
        self,
        repo_path: str,
        subdir: str,
        filename: str,
        content: str,
    ) -> str:
        test_dir = Path(repo_path) / subdir
        test_dir.mkdir(parents=True, exist_ok=True)
        file_path = test_dir / filename
        file_path.write_text(content)
        return str(file_path)

    def _git_commit(
        self,
        repo_path: str,
        branch: str,
        file_paths: list[str],
    ) -> None:
        try:
            subprocess.run(
                ["git", "checkout", branch],
                capture_output=True, cwd=repo_path, timeout=self._timeout,
            )
            for fp in file_paths:
                subprocess.run(
                    ["git", "add", fp],
                    capture_output=True, cwd=repo_path,
                )
            subprocess.run(
                ["git", "commit", "-m", "test: auto-generate tests for feature"],
                capture_output=True, cwd=repo_path,
            )
            subprocess.run(
                ["git", "push"],
                capture_output=True, cwd=repo_path, timeout=self._timeout,
            )
        except Exception as exc:
            logger.warning("test_git_commit_failed", branch=branch, error=str(exc))
