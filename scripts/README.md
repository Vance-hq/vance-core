# scripts

One-off setup and migration utilities.

## Planned scripts

| Script | Purpose |
|---|---|
| `setup_vps.sh` | Bootstrap Contabo VPS: Docker, WireGuard, system deps |
| `rotate_secrets.py` | Rotate agent shared secrets and update Redis |
| `seed_db.py` | Seed initial Postgres data for local dev |
| `health_check.py` | Quick CLI check of all agent /health endpoints |

Add scripts here as they're written. Every script must read all config from environment variables.
