"""DDoS responder — detect traffic spikes, enable Under Attack mode, auto-restore."""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger

from .db import SecurityDB

logger = get_logger(__name__)

SPIKE_MULTIPLIER = 10.0
UNDER_ATTACK_SECURITY_LEVEL = "under_attack"
NORMAL_SECURITY_LEVEL = "medium"


class DDoSResponder:

    def __init__(self, db: SecurityDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._zone_ids: list[str] = cfg.get("cloudflare_zone_ids", [])
        self._baseline_rps: float = float(cfg.get("baseline_rps", 100.0))

    # ------------------------------------------------------------------

    def respond(self, zone_id: str | None = None) -> dict[str, Any]:
        """Full DDoS check-response cycle for one zone (or all configured zones)."""
        zones = [zone_id] if zone_id else self._zone_ids
        if not zones:
            return {"zones_checked": 0, "attacks_detected": 0}

        attacks_detected = 0
        for zone in zones:
            metrics = self.check_traffic(zone)
            if self.is_attack(metrics, {"baseline_rps": self._baseline_rps}):
                self.enable_under_attack(zone)
                self._create_rate_limit_rule(zone, metrics)
                self._db.save_event(
                    event_type="ddos_detected",
                    severity="CRITICAL",
                    target=zone,
                    action_taken="under_attack_mode_enabled",
                    details=metrics,
                )
                attacks_detected += 1
                logger.warning("ddos_attack_detected", zone=zone, rps=metrics.get("rps"))

        return {"zones_checked": len(zones), "attacks_detected": attacks_detected}

    def check_traffic(self, zone_id: str) -> dict[str, Any]:
        """Query Cloudflare analytics for current request rate."""
        try:
            from agents.integrations.connectors.cloudflare import CloudflareConnector

            cf = CloudflareConnector(called_by="security", method_name="get_analytics")
            data = cf.get_analytics(zone_id=zone_id, since="-5")
            totals = data.get("result", {}).get("totals", {})
            requests = totals.get("requests", {}).get("all", 0)
            rps = requests / 300.0

            unique_ips = totals.get("uniques", {}).get("all", 0)
            referrers = data.get("result", {}).get("timeseries", [])

            return {
                "zone_id": zone_id,
                "rps": rps,
                "requests_5min": requests,
                "unique_ips": unique_ips,
                "raw": data,
            }
        except Exception as exc:
            logger.error("cloudflare_analytics_failed", zone=zone_id, error=str(exc))
            return {"zone_id": zone_id, "rps": 0.0, "requests_5min": 0, "unique_ips": 0}

    def is_attack(self, metrics: dict[str, Any], baseline: dict[str, Any]) -> bool:
        """Return True if traffic is 10x baseline and looks automated."""
        rps = metrics.get("rps", 0.0)
        baseline_rps = baseline.get("baseline_rps", self._baseline_rps)
        is_spike = rps >= baseline_rps * SPIKE_MULTIPLIER
        is_automated = self._looks_automated(metrics)
        return is_spike and is_automated

    def enable_under_attack(self, zone_id: str) -> bool:
        """Set Cloudflare security level to 'under_attack'."""
        return self._set_security_level(zone_id, UNDER_ATTACK_SECURITY_LEVEL)

    def disable_under_attack(self, zone_id: str) -> bool:
        """Restore normal Cloudflare security level after traffic normalizes."""
        success = self._set_security_level(zone_id, NORMAL_SECURITY_LEVEL)
        if success:
            self._db.save_event(
                event_type="ddos_mitigated",
                severity="INFO",
                target=zone_id,
                action_taken="under_attack_mode_disabled",
            )
        return success

    # ------------------------------------------------------------------

    def _set_security_level(self, zone_id: str, level: str) -> bool:
        try:
            from agents.integrations.connectors.cloudflare import CloudflareConnector

            cf = CloudflareConnector(called_by="security", method_name="set_security_level")
            cf.set_zone_security_level(zone_id=zone_id, level=level)
            logger.info("cloudflare_security_level_set", zone=zone_id, level=level)
            return True
        except Exception as exc:
            logger.error("cloudflare_set_level_failed", zone=zone_id, error=str(exc))
            return False

    def _create_rate_limit_rule(self, zone_id: str, metrics: dict[str, Any]) -> None:
        try:
            from agents.integrations.connectors.cloudflare import CloudflareConnector

            cf = CloudflareConnector(called_by="security", method_name="create_waf_rule")
            cf.create_custom_firewall_rule(
                zone_id=zone_id,
                expression='(http.request.uri.path contains "/") and (ip.src ne 0.0.0.0/0)',
                action="rate_limit",
                description="Auto rate-limit: DDoS response",
            )
        except Exception as exc:
            logger.warning("rate_limit_rule_failed", zone=zone_id, error=str(exc))

    def _looks_automated(self, metrics: dict[str, Any]) -> bool:
        """Heuristic: very high request rate from few unique IPs → automated."""
        rps = metrics.get("rps", 0.0)
        unique_ips = metrics.get("unique_ips", 1) or 1
        rps_per_ip = rps / unique_ips
        return rps_per_ip > 50.0
