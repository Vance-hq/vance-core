# infra/wireguard

WireGuard VPN tunnel — local machine ↔ Contabo VPS.

## Peer configuration

| Peer | Address | Role |
|---|---|---|
| Local machine | `10.10.0.1/24` | Orchestrator, voice, dashboard |
| Contabo VPS | `10.10.0.2/24` | All agents, Redis, Postgres, nginx |

## Files (Phase 7 — do not commit private keys)

```
wireguard/
├── wg0-local.conf.example     # Local peer config template
└── wg0-server.conf.example    # VPS server config template
```

Actual `.conf` files with private keys belong on the respective machine only, never in version control.

## Setup

```bash
# VPS
wg-quick up /etc/wireguard/wg0.conf

# Local
sudo wg-quick up infra/wireguard/wg0-local.conf
```
