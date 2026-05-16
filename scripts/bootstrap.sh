#!/usr/bin/env bash
# One-shot bootstrap for a fresh DigitalOcean Ubuntu 24.04 droplet
# hosting meeting-copilot. Idempotent — safe to re-run.
#
# Usage on the droplet (as root):
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/Garage/server/meeting-copilot/scripts/bootstrap.sh | bash
# or:
#   ssh root@<droplet-ip> 'bash -s' < bootstrap.sh

set -euo pipefail

DEPLOY_PATH="/opt/copilot"
DOMAIN="copilot.networkchains.com"

echo "==> apt update + base tools"
apt-get update -y
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg lsb-release ufw nginx \
    rsync htop

# ── Swap (2 GB) — safety net on a 4 GB droplet so a momentary spike
#    doesn't OOM-kill Postgres mid-write.
if ! swapon --show | grep -q '/swapfile'; then
    echo "==> Creating 2 GB swap file"
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    if ! grep -q '/swapfile' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi
    # Prefer keeping pages resident; only swap under real pressure.
    sysctl -w vm.swappiness=10
    echo 'vm.swappiness=10' > /etc/sysctl.d/99-copilot-swappiness.conf
fi

# ── Docker engine + compose plugin
if ! command -v docker >/dev/null 2>&1; then
    echo "==> Installing Docker"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
fi

# ── Deploy dirs
mkdir -p "${DEPLOY_PATH}"

# ── Firewall — only the public-facing ports. Postgres / Redis /
#    Qdrant live on the docker internal network; ai-service +
#    realtime-gateway are bound to 127.0.0.1 only (nginx fronts).
echo "==> Configuring ufw"
ufw allow OpenSSH
ufw allow 'Nginx Full'
yes | ufw enable

# ── Nginx — sites-available exists, but the vhost file itself is
#    rsynced in by the GHA deploy workflow. Until that has run, we
#    just want nginx itself to be running.
systemctl enable --now nginx

# ── TLS via certbot (first time only). Wildcard cert holders can
#    skip this and symlink the existing cert dir instead.
if ! command -v certbot >/dev/null 2>&1; then
    echo "==> Installing certbot"
    apt-get install -y certbot python3-certbot-nginx
fi

cat <<EOF

──────────────────────────────────────────────────────────────────────
Bootstrap done.

Next steps (you, on this droplet):
1. Add ${DEPLOY_PATH}/.env  (see docker-compose.deploy.yml header for keys)
2. Point DNS:  ${DOMAIN} A → \$(curl -s ifconfig.me)
3. Wait for the GHA deploy job to push docker-compose.deploy.yml +
   the nginx vhost (or rsync them manually for the first deploy).
4. Issue TLS cert:
       certbot --nginx -d ${DOMAIN} --redirect --agree-tos -m you@example.com
5. Tail logs:  docker compose -f ${DEPLOY_PATH}/docker-compose.deploy.yml logs -f
──────────────────────────────────────────────────────────────────────
EOF
