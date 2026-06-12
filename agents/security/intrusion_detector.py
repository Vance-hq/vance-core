"""Intrusion detector — log analysis, attack pattern detection, auto-remediation."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx

from shared.config.settings import settings
from shared.llm.client import llm
from shared.logger import get_logger

from .db import SecurityDB

logger = get_logger(__name__)

# Detection thresholds
FAILED_LOGIN_THRESHOLD = 5
FAILED_LOGIN_WINDOW_MINUTES = 5
PORT_SCAN_THRESHOLD = 10
PORT_SCAN_WINDOW_SECONDS = 60

_SQL_INJECTION_PATTERNS = re.compile(
    r"(\bunion\b.*\bselect\b|\bselect\b.*\bfrom\b|\bdrop\s+table\b"
    r"|\binsert\s+into\b|\bdelete\s+from\b|'--|\bor\b\s+['\d]+=\s*['\d]+"
    r"|;.*\bdrop\b|xp_cmdshell|exec\s*\()",
    re.IGNORECASE,
)
_XSS_PATTERNS = re.compile(
    r"(<script|javascript:|onerror=|onload=|<img[^>]+src\s*=\s*[\"']?javascript"
    r"|<iframe|document\.cookie|eval\s*\()",
    re.IGNORECASE,
)


class IntrusionDetector:

    def __init__(self, db: SecurityDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._loki_url: str = cfg.get("loki_url", settings.LOKI_URL)
        self._cf_zone_ids: list[str] = cfg.get("cloudflare_zone_ids", [])

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def scan(self, log_entries: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Process a batch of log entries. Returns findings dict with:
          - blocked_ips: IPs auto-blocked via Cloudflare
          - attack_patterns: SQL injection / XSS / port scan findings
          - llm_triage: LLM assessment for ambiguous patterns
        """
        findings: dict[str, Any] = {
            "blocked_ips": [],
            "attack_patterns": [],
            "llm_triage": None,
        }

        ips_to_block = self.check_failed_logins(log_entries)
        attack_hits = self.check_attack_patterns(log_entries)
        port_scan_ips = self.check_port_scans(log_entries)

        all_bad_ips = list({*ips_to_block, *port_scan_ips})

        for ip in all_bad_ips:
            blocked = self.block_ip(ip, reason="auto: threshold exceeded")
            if blocked:
                findings["blocked_ips"].append(ip)
                self._db.save_event(
                    event_type="ip_blocked",
                    severity="HIGH",
                    source_ip=ip,
                    action_taken="cloudflare_block",
                )

        for hit in attack_hits:
            self._db.save_event(
                event_type=hit["type"],
                severity="HIGH",
                source_ip=hit.get("ip"),
                target=hit.get("path"),
                details=hit,
            )

        findings["attack_patterns"] = attack_hits

        ambiguous = [e for e in log_entries if self._is_ambiguous(e)]
        if ambiguous:
            findings["llm_triage"] = self.triage_with_llm(ambiguous[:20])

        return findings

    def check_failed_logins(self, entries: list[dict[str, Any]]) -> list[str]:
        """Return IPs with >FAILED_LOGIN_THRESHOLD failed logins in the detection window."""
        by_ip: dict[str, list[datetime]] = defaultdict(list)
        for entry in entries:
            if not entry.get("failed_login"):
                continue
            ip = entry.get("ip", "")
            ts = entry.get("timestamp")
            if ip and ts:
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                by_ip[ip].append(ts)

        offenders: list[str] = []
        for ip, timestamps in by_ip.items():
            timestamps.sort()
            window_start = timestamps[-1].timestamp() - FAILED_LOGIN_WINDOW_MINUTES * 60
            in_window = sum(1 for t in timestamps if t.timestamp() >= window_start)
            if in_window > FAILED_LOGIN_THRESHOLD:
                offenders.append(ip)

        return offenders

    def check_attack_patterns(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect SQL injection and XSS patterns in request logs."""
        hits: list[dict[str, Any]] = []
        for entry in entries:
            request = entry.get("request", "") or ""
            path = entry.get("path", "") or ""
            body = entry.get("body", "") or ""
            combined = f"{request} {path} {body}"

            if _SQL_INJECTION_PATTERNS.search(combined):
                hits.append({
                    "type": "sql_injection",
                    "ip": entry.get("ip"),
                    "path": entry.get("path", request[:200]),
                })
            elif _XSS_PATTERNS.search(combined):
                hits.append({
                    "type": "xss_attempt",
                    "ip": entry.get("ip"),
                    "path": entry.get("path", request[:200]),
                })

        return hits

    def check_port_scans(self, entries: list[dict[str, Any]]) -> list[str]:
        """Return IPs that hit many distinct ports in a short window."""
        by_ip: dict[str, dict[int, float]] = defaultdict(dict)
        for entry in entries:
            ip = entry.get("ip", "")
            port = entry.get("port")
            ts = entry.get("timestamp")
            if not (ip and port and ts):
                continue
            if isinstance(ts, str):
                try:
                    ts_f = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
            elif isinstance(ts, datetime):
                ts_f = ts.timestamp()
            else:
                ts_f = float(ts)
            by_ip[ip][int(port)] = ts_f

        scanners: list[str] = []
        for ip, port_times in by_ip.items():
            if len(port_times) >= PORT_SCAN_THRESHOLD:
                times = list(port_times.values())
                window = max(times) - min(times)
                if window <= PORT_SCAN_WINDOW_SECONDS:
                    scanners.append(ip)

        return scanners

    def block_ip(self, ip: str, zone_id: str | None = None, reason: str = "") -> bool:
        """Block IP via Cloudflare. Returns True if successful."""
        try:
            from agents.integrations.connectors.cloudflare import CloudflareConnector

            cf = CloudflareConnector(called_by="security", method_name="block_ip")
            zone = zone_id or (self._cf_zone_ids[0] if self._cf_zone_ids else "")
            if not zone:
                logger.warning("no_cloudflare_zone_configured")
                return False

            cf.block_ip_access_rule(zone_id=zone, ip=ip, notes=reason)
            logger.info("ip_blocked_cloudflare", ip=ip, zone=zone)
            return True
        except Exception as exc:
            logger.error("cloudflare_block_failed", ip=ip, error=str(exc))
            return False

    def triage_with_llm(self, entries: list[dict[str, Any]]) -> str:
        """Ask LLM whether ambiguous patterns are real attacks or noise."""
        sample = "\n".join(
            f"IP={e.get('ip')} path={e.get('path', '')} status={e.get('status', '')}"
            for e in entries[:10]
        )
        prompt = (
            f"Analyze these HTTP log entries and determine if they represent a real "
            f"attack pattern or normal traffic noise. Be concise.\n\n{sample}"
        )
        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system="You are a security analyst. Assess whether log patterns are genuine threats.",
            metadata={"caller": "security.intrusion_detector"},
        ).content[0].text

    # ------------------------------------------------------------------

    def query_loki(self, logql: str, hours: int = 1) -> list[dict[str, Any]]:
        """Query Loki for log entries matching a LogQL expression."""
        try:
            end = datetime.now(timezone.utc)
            start_ns = int((end.timestamp() - hours * 3600) * 1e9)
            end_ns = int(end.timestamp() * 1e9)
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{self._loki_url}/loki/api/v1/query_range",
                    params={"query": logql, "start": start_ns, "end": end_ns, "limit": 5000},
                )
                if not resp.is_success:
                    return []
                data = resp.json()
                entries: list[dict[str, Any]] = []
                for stream in data.get("data", {}).get("result", []):
                    labels = stream.get("stream", {})
                    for ts_ns, line in stream.get("values", []):
                        entries.append({"timestamp": ts_ns, "line": line, **labels})
                return entries
        except Exception as exc:
            logger.warning("loki_query_failed", error=str(exc))
            return []

    def _is_ambiguous(self, entry: dict[str, Any]) -> bool:
        path = entry.get("path", "") or ""
        status = entry.get("status", 200)
        return (
            status in (400, 403, 404, 429)
            and not _SQL_INJECTION_PATTERNS.search(path)
            and not _XSS_PATTERNS.search(path)
        )
