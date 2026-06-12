#!/usr/bin/env bash
# Starts the Vance ops tools stack (monitoring, analytics, wiki, CRM, feature flags).
# Run once after filling in TOOLS_* variables in .env.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/infra/docker/docker-compose.tools.yml"
ENV_FILE="${REPO_ROOT}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "ERROR: .env not found at ${ENV_FILE}. Copy .env.example and fill in values first."
    exit 1
fi

echo "=== Vance Tools Stack ==="
echo "Starting: Grafana · Prometheus · Loki · Uptime Kuma · Umami · Unleash · Outline · Twenty CRM"
echo ""

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d

echo ""
echo "=== Tools ready ==="
printf "  %-14s  %s\n" "Grafana"      "http://localhost:3010   (admin / \$GRAFANA_ADMIN_PASSWORD)"
printf "  %-14s  %s\n" "Prometheus"   "http://localhost:9090"
printf "  %-14s  %s\n" "Uptime Kuma"  "http://localhost:3001   (configure on first visit)"
printf "  %-14s  %s\n" "Umami"        "http://localhost:3020   (admin / umami — change on first login)"
printf "  %-14s  %s\n" "Unleash"      "http://localhost:4242   (admin@getunleash.io / unleash4all — change immediately)"
printf "  %-14s  %s\n" "Outline"      "http://localhost:3030"
printf "  %-14s  %s\n" "Twenty CRM"   "http://localhost:3040"
echo ""
echo "Logs: docker compose -f ${COMPOSE_FILE} logs -f"
echo "Stop: docker compose -f ${COMPOSE_FILE} down"
