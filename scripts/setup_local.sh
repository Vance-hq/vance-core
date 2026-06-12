#!/usr/bin/env bash
# setup_local.sh — configure the local machine to connect to the Vance VPS
# Installs: WireGuard client, Redis (local task queue)
# Generates a WireGuard keypair and outputs the public key for the server config.
set -euo pipefail

log()  { echo "[setup_local] $*"; }
warn() { echo "[setup_local] WARNING: $*"; }
die()  { echo "[ERROR] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Detect OS and install packages
# ---------------------------------------------------------------------------
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux (Ubuntu/Debian assumed)
    [[ $EUID -eq 0 ]] || die "Run as root on Linux (sudo bash setup_local.sh)"

    apt-get update -qq
    log "Installing WireGuard and Redis..."
    apt-get install -y --no-install-recommends wireguard redis-server

    systemctl enable --now redis-server
    log "Redis started on 127.0.0.1:6379"

elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    command -v brew &>/dev/null || die "Homebrew not found. Install it from https://brew.sh"

    log "Installing WireGuard tools and Redis via Homebrew..."
    brew install wireguard-tools redis

    brew services start redis
    log "Redis started on 127.0.0.1:6379"

else
    die "Unsupported OS: $OSTYPE. Install WireGuard and Redis manually."
fi

# ---------------------------------------------------------------------------
# 2. Generate WireGuard keypair
# ---------------------------------------------------------------------------
WG_DIR="${HOME}/.config/wireguard"
mkdir -p "${WG_DIR}"
chmod 700 "${WG_DIR}"

PRIVATE_KEY_FILE="${WG_DIR}/vance_client_private.key"
PUBLIC_KEY_FILE="${WG_DIR}/vance_client_public.key"

if [[ -f "${PRIVATE_KEY_FILE}" ]]; then
    log "WireGuard keypair already exists — skipping generation"
else
    log "Generating WireGuard keypair..."
    wg genkey | tee "${PRIVATE_KEY_FILE}" | wg pubkey > "${PUBLIC_KEY_FILE}"
    chmod 600 "${PRIVATE_KEY_FILE}"
fi

PUBLIC_KEY=$(cat "${PUBLIC_KEY_FILE}")

# ---------------------------------------------------------------------------
# 3. Generate client config from template
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/../infra/wireguard/local-client.conf.template"
WG_CONF_OUT="${WG_DIR}/wg0.conf"

if [[ -f "${WG_CONF_OUT}" ]]; then
    warn "WireGuard config already exists at ${WG_CONF_OUT} — not overwriting"
else
    log "Generating ${WG_CONF_OUT} from template..."
    PRIVATE_KEY=$(cat "${PRIVATE_KEY_FILE}")
    sed \
        -e "s|CLIENT_PRIVATE_KEY|${PRIVATE_KEY}|g" \
        -e "s|SERVER_PUBLIC_KEY|REPLACE_WITH_VPS_PUBLIC_KEY|g" \
        -e "s|SERVER_ENDPOINT|REPLACE_WITH_VPS_IP:51820|g" \
        "${TEMPLATE}" > "${WG_CONF_OUT}"
    chmod 600 "${WG_CONF_OUT}"
fi

# ---------------------------------------------------------------------------
# 4. Summary
# ---------------------------------------------------------------------------
echo ""
echo "======================================================"
echo "  Local setup complete."
echo ""
echo "  YOUR WireGuard PUBLIC KEY (add to VPS wg0.conf):"
echo "  ${PUBLIC_KEY}"
echo ""
echo "  Next steps:"
echo "  1. SSH into the VPS and add the [Peer] block:"
echo "     [Peer]"
echo "     PublicKey  = ${PUBLIC_KEY}"
echo "     AllowedIPs = 10.99.0.2/32"
echo ""
echo "  2. Reload WireGuard on the VPS (no downtime):"
echo "     wg addconf wg0 <(wg-quick strip wg0)"
echo ""
echo "  3. Edit ${WG_CONF_OUT}:"
echo "     Replace REPLACE_WITH_VPS_PUBLIC_KEY and REPLACE_WITH_VPS_IP"
echo ""
echo "  4. Start the tunnel:"
echo "     wg-quick up ${WG_CONF_OUT}"
echo ""
echo "  5. Verify:"
echo "     ping 10.99.0.1"
echo "     curl http://10.99.0.1:7700/health"
echo "======================================================"
