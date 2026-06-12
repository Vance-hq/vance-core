# core/orchestrator

Task router, intent handler, and priority queue manager. Runs locally.

## Responsibilities

1. Receive parsed `IntentResult` from `core/voice` or the dashboard.
2. Validate confidence threshold before dispatch.
3. Push tasks onto the Redis queue for the appropriate agent.
4. Heartbeat all VPS agents over WireGuard; alert if any go offline.

## Running locally

```bash
python -m core.orchestrator.main
```

## WireGuard dependency

All agent communication goes over the WireGuard tunnel (`wg0`). If the tunnel is down, the orchestrator queues tasks locally and retries on reconnect. Configure the tunnel via `infra/wireguard/` before running in production.
