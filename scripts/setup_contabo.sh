#!/usr/bin/env bash
# setup_contabo.sh — bootstrap a fresh Contabo VPS for Vance
# Run as root on a fresh Ubuntu 22.04 LTS instance.
# Does NOT touch Mailcow or any existing docker-compose stacks.
set -euo pipefail

VANCE_USER="vance"
REPO_URL="https://github.com/Vance-hq/vance.git"
VANCE_DIR="/home/${VANCE_USER}/vance"

log() { echo "[setup_contabo] $*"; }
die() { echo "[ERROR] $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root (sudo bash setup_contabo.sh)"

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
log "Updating package list..."
apt-get update -qq

log "Installing Docker dependencies..."
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg lsb-release

# Docker official GPG + repo
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list

apt-get update -qq
log "Installing Docker CE, Compose plugin, WireGuard, Nginx, Certbot..."
apt-get install -y --no-install-recommends \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin \
    wireguard \
    nginx \
    certbot \
    python3-certbot-nginx \
    git \
    curl

systemctl enable --now docker nginx

# ---------------------------------------------------------------------------
# 2. System user
# ---------------------------------------------------------------------------
if ! id "${VANCE_USER}" &>/dev/null; then
    log "Creating system user: ${VANCE_USER}"
    useradd -r -m -s /bin/bash "${VANCE_USER}"
fi
usermod -aG docker "${VANCE_USER}"

# ---------------------------------------------------------------------------
# 3. Clone repo
# ---------------------------------------------------------------------------
if [[ -d "${VANCE_DIR}" ]]; then
    log "Repo already exists at ${VANCE_DIR} — pulling latest..."
    sudo -u "${VANCE_USER}" git -C "${VANCE_DIR}" pull
else
    log "Cloning repo to ${VANCE_DIR}..."
    sudo -u "${VANCE_USER}" git clone "${REPO_URL}" "${VANCE_DIR}"
fi

# ---------------------------------------------------------------------------
# 4. Environment file
# ---------------------------------------------------------------------------
ENV_FILE="${VANCE_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    log "Creating .env from .env.example..."
    sudo -u "${VANCE_USER}" cp "${VANCE_DIR}/.env.example" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    echo ""
    echo "============================================================"
    echo "  ACTION REQUIRED: Fill in secrets in ${ENV_FILE}"
    echo "  Required keys: ANTHROPIC_API_KEY, REDIS_PASSWORD,"
    echo "                 POSTGRES_PASSWORD, ORCHESTRATOR_SECRET_KEY"
    echo "  Then re-run: sudo -u ${VANCE_USER} bash ${VANCE_DIR}/scripts/start_vance.sh"
    echo "============================================================"
    echo ""
else
    log ".env already exists — skipping copy"
fi

# ---------------------------------------------------------------------------
# 5. Nginx config
# ---------------------------------------------------------------------------
NGINX_CONF="/etc/nginx/sites-enabled/vance"
if [[ ! -L "${NGINX_CONF}" ]]; then
    log "Linking nginx config..."
    ln -s "${VANCE_DIR}/infra/nginx/vance.conf" "${NGINX_CONF}"
    # Disable default site if present
    rm -f /etc/nginx/sites-enabled/default
    log "Remember to replace YOUR_DOMAIN_HERE in infra/nginx/vance.conf and run certbot."
fi

# ---------------------------------------------------------------------------
# 6. IP forwarding (needed for WireGuard NAT)
# ---------------------------------------------------------------------------
if ! grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf; then
    log "Enabling IP forwarding..."
    echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
    sysctl -p
fi

# ---------------------------------------------------------------------------
# 7. Start Vance stack
# ---------------------------------------------------------------------------
log "Building and starting Vance Docker stack..."
cd "${VANCE_DIR}"
sudo -u "${VANCE_USER}" docker compose \
    -f infra/docker/docker-compose.vance.yml \
    up -d --build

log ""
log "======================================================"
log "  Vance stack started."
log ""
log "  Next steps:"
log "  1. Fill in secrets: ${ENV_FILE}"
log "  2. Set up WireGuard: see infra/wireguard/wg0.conf.template"
log "  3. Obtain SSL cert: certbot --nginx -d YOUR_DOMAIN"
log "  4. Restart nginx: systemctl restart nginx"
log "  5. Verify: docker compose -f infra/docker/docker-compose.vance.yml ps"
log "======================================================"
