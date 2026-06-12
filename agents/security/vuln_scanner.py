"""Vulnerability scanner — npm audit, pip-audit, Trivy for Docker images."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from shared.logger import get_logger

from .db import SecurityDB

logger = get_logger(__name__)

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _cvss_to_severity(score: float | None) -> str:
    if score is None:
        return "LOW"
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW"


class VulnScanner:

    def __init__(self, db: SecurityDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._repos: list[dict[str, str]] = cfg.get("repos", [])

    # ------------------------------------------------------------------

    def scan_npm(self, repo_path: str) -> list[dict[str, Any]]:
        """Run npm audit --json and return parsed vulnerability list."""
        try:
            result = subprocess.run(
                ["npm", "audit", "--json"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            data = json.loads(result.stdout or "{}")
            return self._parse_npm_audit(data)
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as exc:
            logger.warning("npm_audit_failed", repo=repo_path, error=str(exc))
            return []

    def scan_pip(self, repo_path: str) -> list[dict[str, Any]]:
        """Run pip-audit and return parsed vulnerability list."""
        try:
            result = subprocess.run(
                ["pip-audit", "--format", "json", "--progress-spinner", "off"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=180,
            )
            data = json.loads(result.stdout or "[]")
            return self._parse_pip_audit(data)
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as exc:
            logger.warning("pip_audit_failed", repo=repo_path, error=str(exc))
            return []

    def scan_docker(self, image: str) -> list[dict[str, Any]]:
        """Run trivy image --format json and return parsed vulnerability list."""
        try:
            result = subprocess.run(
                ["trivy", "image", "--format", "json", "--quiet", image],
                capture_output=True,
                text=True,
                timeout=300,
            )
            data = json.loads(result.stdout or "{}")
            return self._parse_trivy(data)
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as exc:
            logger.warning("trivy_scan_failed", image=image, error=str(exc))
            return []

    def classify(self, finding: dict[str, Any]) -> str:
        """Classify a finding by CVSS score into CRITICAL/HIGH/MEDIUM/LOW."""
        score = finding.get("cvss_score") or finding.get("severity_score")
        if isinstance(score, (int, float)):
            return _cvss_to_severity(float(score))
        sev = (finding.get("severity") or "LOW").upper()
        return sev if sev in _SEVERITY_ORDER else "LOW"

    def process_repo(self, repo_path: str, repo_name: str) -> dict[str, Any]:
        """Full vulnerability scan: npm + pip. Returns findings by severity."""
        all_findings: list[dict[str, Any]] = []
        all_findings.extend(self.scan_npm(repo_path))
        all_findings.extend(self.scan_pip(repo_path))

        critical, high, medium, low = [], [], [], []
        for f in all_findings:
            sev = self.classify(f)
            f["severity"] = sev
            self._db.save_vulnerability(
                repo=repo_name,
                package=f.get("package", "unknown"),
                severity=sev,
                scan_type=f.get("scan_type", "unknown"),
                cve_id=f.get("cve_id"),
                cvss_score=f.get("cvss_score"),
                details=f,
            )
            {"CRITICAL": critical, "HIGH": high, "MEDIUM": medium, "LOW": low}[sev].append(f)

        return {
            "repo": repo_name,
            "CRITICAL": critical,
            "HIGH": high,
            "MEDIUM": medium,
            "LOW": low,
            "total": len(all_findings),
        }

    def scan_all_repos(self) -> list[dict[str, Any]]:
        """Scan all configured repos."""
        results = []
        for repo in self._repos:
            path = repo.get("path", "")
            name = repo.get("name", path)
            results.append(self.process_repo(path, name))
            if repo.get("docker_image"):
                docker_findings = self.scan_docker(repo["docker_image"])
                for f in docker_findings:
                    sev = self.classify(f)
                    f["severity"] = sev
                    self._db.save_vulnerability(
                        repo=name,
                        package=f.get("package", "unknown"),
                        severity=sev,
                        scan_type="docker",
                        cve_id=f.get("cve_id"),
                        cvss_score=f.get("cvss_score"),
                        details=f,
                    )
        return results

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    def _parse_npm_audit(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        vulnerabilities = data.get("vulnerabilities", {})
        for pkg_name, vuln in vulnerabilities.items():
            cvss = None
            via = vuln.get("via", [])
            if via and isinstance(via[0], dict):
                cvss = via[0].get("cvss", {}).get("score")
            findings.append({
                "package": pkg_name,
                "scan_type": "npm",
                "cvss_score": cvss,
                "cve_id": via[0].get("url", "").split("/")[-1] if via and isinstance(via[0], dict) else None,
                "severity": (vuln.get("severity") or "low").upper(),
            })
        return findings

    def _parse_pip_audit(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for item in data:
            for vuln in item.get("vulns", []):
                findings.append({
                    "package": item.get("name", ""),
                    "scan_type": "pip",
                    "cve_id": vuln.get("id"),
                    "cvss_score": None,
                    "severity": "MEDIUM",
                    "description": vuln.get("description", ""),
                })
        return findings

    def _parse_trivy(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for result in data.get("Results", []):
            for vuln in result.get("Vulnerabilities", []):
                findings.append({
                    "package": vuln.get("PkgName", ""),
                    "scan_type": "docker",
                    "cve_id": vuln.get("VulnerabilityID"),
                    "cvss_score": vuln.get("CVSS", {}).get("nvd", {}).get("V3Score"),
                    "severity": (vuln.get("Severity") or "LOW").upper(),
                })
        return findings
