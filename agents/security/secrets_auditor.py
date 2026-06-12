"""Secrets auditor — gitleaks scanning, LLM severity triage. Never logs secret values."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import SecurityDB

logger = get_logger(__name__)

_SECRET_REDACT = "[REDACTED]"


class SecretsAuditor:

    def __init__(self, db: SecurityDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._repos: list[dict[str, str]] = cfg.get("repos", [])

    # ------------------------------------------------------------------

    def scan_repo(self, repo_path: str) -> list[dict[str, Any]]:
        """
        Run gitleaks on full git history. Returns findings with secret values stripped.
        CRITICAL: never include actual secret values in return value or logs.
        """
        try:
            result = subprocess.run(
                [
                    "gitleaks",
                    "detect",
                    "--source", repo_path,
                    "--format", "json",
                    "--no-banner",
                    "--log-level", "error",
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            raw = json.loads(result.stdout or "[]")
            return [self._sanitize(f) for f in raw]
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("gitleaks_not_available", repo=repo_path, error=str(exc))
            return []
        except json.JSONDecodeError:
            return []

    def assess_severity(self, finding: dict[str, Any]) -> str:
        """
        Ask LLM: is this a test/dev key or a real production credential?
        Returns: CRITICAL | HIGH | MEDIUM | LOW
        Finding must NOT contain the actual secret value.
        """
        prompt = (
            f"A secrets scan found a potential credential leak.\n"
            f"Rule: {finding.get('RuleID', 'unknown')}\n"
            f"Description: {finding.get('Description', '')}\n"
            f"File: {finding.get('File', '')}\n"
            f"Commit: {finding.get('Commit', '')}\n\n"
            f"Classify severity as exactly one of: CRITICAL, HIGH, MEDIUM, LOW.\n"
            f"CRITICAL = production database/API key. LOW = test/example value.\n"
            f"Reply with just the severity word."
        )
        try:
            response = llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system="You are a security analyst classifying leaked credential severity.",
                metadata={"caller": "security.secrets_auditor"},
            )
            text = response.content[0].text.strip().upper()
            return text if text in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else "HIGH"
        except Exception:
            return "HIGH"

    def scan_all_repos(self) -> dict[str, Any]:
        """Scan all configured repos and record CRITICAL findings as security events."""
        total_findings: list[dict[str, Any]] = []

        for repo in self._repos:
            path = repo.get("path", "")
            name = repo.get("name", path)
            findings = self.scan_repo(path)

            for f in findings:
                severity = self.assess_severity(f)
                f["assessed_severity"] = severity
                self._db.save_event(
                    event_type="leaked_secret",
                    severity=severity,
                    target=f.get("File"),
                    action_taken="credential_rotation_needed",
                    details={
                        "repo": name,
                        "rule_id": f.get("RuleID"),
                        "description": f.get("Description"),
                        "file": f.get("File"),
                        "line": f.get("StartLine"),
                        "commit": f.get("Commit"),
                    },
                )
                total_findings.append({**f, "repo": name})

        return {"findings": total_findings, "total": len(total_findings)}

    # ------------------------------------------------------------------

    def _sanitize(self, finding: dict[str, Any]) -> dict[str, Any]:
        """Strip all secret value fields before returning."""
        safe = {k: v for k, v in finding.items() if k not in ("Secret", "Match")}
        safe["Secret"] = _SECRET_REDACT
        safe["Match"] = _SECRET_REDACT
        return safe
