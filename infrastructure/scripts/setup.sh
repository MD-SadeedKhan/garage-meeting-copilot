#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Garage Meeting Copilot — Deployment Setup Script
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   Garage Meeting Copilot — Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Check prerequisites ────────────────────────────────────────────────────────

check_command() {
    if ! command -v "$1" &>/dev/null; then
        log_error "$1 is not installed. Please install it and retry."
    fi
    log_success "$1 found: $(command -v "$1")"
}

log_info "Checking prerequisites..."
check_command docker
check_command docker-compose || check_command "docker compose"
check_command git

# ── Environment setup ──────────────────────────────────────────────────────────

cd "$ROOT_DIR"

if [ ! -f ".env" ]; then
    log_info "Creating .env from .env.example..."
    cp .env.example .env
    log_warn "Please edit .env with your credentials before proceeding!"
    log_warn "Required: GARAGE_JWT_SECRET, OPENAI_API_KEY, DEEPGRAM_API_KEY"
    echo ""
    read -p "Press Enter to continue after editing .env, or Ctrl+C to exit..." _
fi

# Generate secure SECRET_KEY if placeholder
if grep -q "change-me-in-production-use-openssl-rand-hex-32" .env; then
    SECRET=$(openssl rand -hex 32)
    sed -i.bak "s/change-me-in-production-use-openssl-rand-hex-32/$SECRET/" .env
    log_success "Generated SECRET_KEY"
fi

# Generate secure POSTGRES_PASSWORD if placeholder
if grep -q "change-me-in-production" .env; then
    PG_PASS=$(openssl rand -base64 24 | tr -d '/')
    REDIS_PASS=$(openssl rand -base64 24 | tr -d '/')
    sed -i.bak "s/POSTGRES_PASSWORD=change-me-in-production/POSTGRES_PASSWORD=$PG_PASS/" .env
    sed -i.bak "s/REDIS_PASSWORD=change-me-in-production/REDIS_PASSWORD=$REDIS_PASS/" .env
    # Update DATABASE_URL and REDIS_URL
    sed -i.bak "s|postgresql+asyncpg://copilot:change-me-in-production@|postgresql+asyncpg://copilot:$PG_PASS@|" .env
    sed -i.bak "s|redis://:change-me-in-production@|redis://:$REDIS_PASS@|" .env
    log_success "Generated secure database passwords"
fi

# ── Docker build ───────────────────────────────────────────────────────────────

log_info "Building Docker images..."
docker compose build --no-cache

log_success "Docker images built"

# ── Start infrastructure ───────────────────────────────────────────────────────

log_info "Starting infrastructure services (postgres, redis, qdrant)..."
docker compose up -d postgres redis qdrant

log_info "Waiting for postgres to be ready..."
until docker compose exec -T postgres pg_isready -U copilot -d garage_copilot &>/dev/null; do
    sleep 1
done
log_success "PostgreSQL ready"

log_info "Waiting for redis to be ready..."
REDIS_PASS=$(grep REDIS_PASSWORD .env | cut -d= -f2)
until docker compose exec -T redis redis-cli -a "$REDIS_PASS" ping &>/dev/null; do
    sleep 1
done
log_success "Redis ready"

log_info "Waiting for Qdrant to be ready..."
until curl -sf http://localhost:6333/readyz &>/dev/null; do
    sleep 1
done
log_success "Qdrant ready"

# ── Database migrations ────────────────────────────────────────────────────────

log_info "Running Alembic database migrations..."
docker compose run --rm meeting-ai-service alembic upgrade head
log_success "Database migrations applied"

# ── Start all services ─────────────────────────────────────────────────────────

log_info "Starting all services..."
docker compose up -d

log_info "Waiting for services to be healthy..."
sleep 5

# Check health endpoints
check_service() {
    local name="$1"
    local url="$2"
    local max_attempts=30
    local attempt=0
    while [ $attempt -lt $max_attempts ]; do
        if curl -sf "$url" &>/dev/null; then
            log_success "$name is healthy"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 2
    done
    log_warn "$name health check timed out (check logs: docker compose logs $name)"
}

check_service "AI Service"      "http://localhost:8080/health"
check_service "Realtime Gateway" "http://localhost:8080/gateway/health"

# ── Summary ────────────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}  Garage Meeting Copilot is running!${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Services:"
echo "  • AI REST API:       http://localhost:8080/api/v1/"
echo "  • WebSocket Gateway: ws://localhost:8080/ws/copilot"
echo "  • Health:            http://localhost:8080/health"
echo ""
echo "  Next steps:"
echo "  1. Build the desktop agent: cd desktop-agent && npm run tauri:build"
echo "  2. Configure Garage JWT secret in .env"
echo "  3. Point Garage frontend to ws://localhost:8080/ws/copilot"
echo ""
echo "  Logs: docker compose logs -f"
echo ""
