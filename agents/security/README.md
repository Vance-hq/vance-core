# agents/security

Uptime monitoring, log anomaly detection, and alerting.

## Capabilities

| Action | Description |
|---|---|
| `check_uptime` | HTTP health checks for all configured target URLs |
| `scan_logs` | Scan VPS logs for anomalies, failed auth, error spikes |
| `send_alert` | Route alert via Mailcow email or orchestrator push |

## Running locally

```bash
SECURITY_AGENT_SECRET=xxx python -m agents.security.main
```

## Configuration

- `SECURITY_UPTIME_TARGETS` — comma-separated list of URLs to monitor.
- `SECURITY_CHECK_INTERVAL_S` — polling interval (default: 60 s).
- Alert thresholds are configured in config.py and should be moved to env vars per environment.
