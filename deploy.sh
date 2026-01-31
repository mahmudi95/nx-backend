#!/bin/bash
set -euo pipefail

# =============================================================================
# NX-Backend Remote Deployment (LOCAL -> GHCR -> HETZNER)
# =============================================================================
# Usage:
#   ./deploy.sh                       # Deploy backend (quick)
#   ./deploy.sh --full                # Restart all services
#   ./deploy.sh --restore /path       # Deploy with DB restore
#   ./deploy.sh --rollback            # Rollback to previous version
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env.prod
if [ -f "$SCRIPT_DIR/.env.prod" ]; then
    source "$SCRIPT_DIR/.env.prod"
else
    echo "ERROR: .env.prod not found. Create it with:"
    cat << 'EOF'
# Remote server
REMOTE_USER=root
REMOTE_HOST=your-server-ip
REMOTE_DIR=/root/nx-backend

# GitHub Container Registry
GITHUB_USER=mahmudi95
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
IMAGE_NAME=ghcr.io/mahmudi95/nx-backend

# Database
POSTGRES_USER=neuraplex
POSTGRES_PASSWORD=yourpassword
POSTGRES_DB=neuraplex

# API Security
API_KEY=your-api-key
EOF
    exit 1
fi

# Required vars
: "${REMOTE_USER:?REMOTE_USER not set}"
: "${REMOTE_HOST:?REMOTE_HOST not set}"
: "${GITHUB_USER:?GITHUB_USER not set}"
: "${GITHUB_TOKEN:?GITHUB_TOKEN not set}"
: "${IMAGE_NAME:?IMAGE_NAME not set}"
REMOTE_DIR="${REMOTE_DIR:-/root/nx-backend}"

# Parse args
RESTORE_PATH=""
ROLLBACK=""
FULL=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --restore|-r) RESTORE_PATH="$2"; shift 2 ;;
        --rollback) ROLLBACK="true"; shift ;;
        --full|-f) FULL="true"; shift ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

# Colors
log() { echo -e "\033[0;32m[✓]\033[0m $1"; }
warn() { echo -e "\033[1;33m[!]\033[0m $1"; }
error() { echo -e "\033[0;31m[✗]\033[0m $1"; exit 1; }

REMOTE="$REMOTE_USER@$REMOTE_HOST"

# SSH helper
run_ssh() { ssh -o StrictHostKeyChecking=accept-new "$REMOTE" "$@"; }
run_rsync() { rsync "$@"; }
remote_docker() { run_ssh "docker $*"; }
remote_compose() { run_ssh "cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml --env-file .env.prod $*"; }

echo "================================================"
echo "   NX-Backend Deploy -> $REMOTE_HOST"
[ -n "$RESTORE_PATH" ] && echo "   Mode: RESTORE"
[ -n "$ROLLBACK" ] && echo "   Mode: ROLLBACK"
[ -n "$FULL" ] && echo "   Mode: FULL"
[ -z "$RESTORE_PATH" ] && [ -z "$ROLLBACK" ] && [ -z "$FULL" ] && echo "   Mode: QUICK"
echo "================================================"

# =============================================================================
# ROLLBACK
# =============================================================================
if [ -n "$ROLLBACK" ]; then
    log "Rolling back to :previous..."
    remote_docker "tag $IMAGE_NAME:previous $IMAGE_NAME:latest" || error "No :previous image"
    remote_compose "up -d --force-recreate backend"
    sleep 5
    remote_compose "ps"
    log "Rollback complete!"
    exit 0
fi

# =============================================================================
# BUILD & PUSH
# =============================================================================
cd "$SCRIPT_DIR"
log "Building image..."
docker build -t "$IMAGE_NAME:latest" .

log "Logging into GHCR..."
echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin

log "Pushing to GHCR..."
docker push "$IMAGE_NAME:latest"

# =============================================================================
# SYNC FILES
# =============================================================================
log "Creating remote directory..."
run_ssh "mkdir -p $REMOTE_DIR/dumps"

log "Syncing files..."
run_rsync -avz docker-compose.prod.yml .env.prod Caddyfile "$REMOTE:$REMOTE_DIR/"

# =============================================================================
# RESTORE MODE
# =============================================================================
if [ -n "$RESTORE_PATH" ]; then
    [ ! -f "$RESTORE_PATH/postgres_all.sql.gz" ] && error "Backup not found: $RESTORE_PATH/postgres_all.sql.gz"
    
    log "Transferring backup..."
    run_rsync -avz --progress "$RESTORE_PATH/postgres_all.sql.gz" "$REMOTE:$REMOTE_DIR/dumps/"
    
    log "Stopping services..."
    remote_compose "down -v" 2>/dev/null || true
    
    log "Starting database..."
    remote_compose "up -d db"
    sleep 15
    
    log "Restoring PostgreSQL..."
    run_ssh "cd $REMOTE_DIR && source .env.prod && gunzip -c dumps/postgres_all.sql.gz | docker exec -i \$(docker compose -f docker-compose.prod.yml ps -q db) psql -U \$POSTGRES_USER -d \$POSTGRES_DB"
    
    log "Starting all services..."
    remote_compose "up -d"
else
    # =============================================================================
    # NORMAL DEPLOY
    # =============================================================================
    log "Logging into GHCR on remote..."
    remote_docker "login ghcr.io -u '$GITHUB_USER' -p '$GITHUB_TOKEN'"
    
    log "Backing up current image..."
    remote_docker "tag $IMAGE_NAME:latest $IMAGE_NAME:previous" 2>/dev/null || warn "No existing image (first deploy)"
    
    log "Pulling latest..."
    remote_docker "pull $IMAGE_NAME:latest"
    
    if [ -n "$FULL" ]; then
        log "Full restart..."
        remote_compose "down" 2>/dev/null || true
        remote_compose "up -d"
    else
        log "Quick deploy (backend only)..."
        remote_compose "up -d --no-deps --force-recreate backend"
    fi
fi

# =============================================================================
# VERIFY
# =============================================================================
log "Waiting for services..."
sleep 10

echo ""
remote_compose "ps"
echo ""
log "Deploy complete!"
echo ""
echo "  API: https://api.palentier.com"
echo "  Health: curl https://api.palentier.com/health"
echo "  Logs: ssh $REMOTE 'docker logs -f \$(docker ps -qf name=backend)'"
echo ""
