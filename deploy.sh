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
#   ./deploy.sh --setup-wireguard     # Force WireGuard setup/reconfigure
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
REMOTE_DIR=/opt/nx-backend

# GitHub Container Registry
GITHUB_USER=mahmudi95
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
IMAGE_NAME=ghcr.io/mahmudi95/nx-backend

# PostgreSQL
POSTGRES_USER=neuraplex
POSTGRES_PASSWORD=yourpassword
POSTGRES_DB=neuraplex

# MongoDB
MONGODB_DB=neuraplex
MONGODB_USERNAME=neuraplex
MONGODB_PASSWORD=yourpassword

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
REMOTE_DIR="${REMOTE_DIR:-/opt/nx-backend}"

# Parse args
RESTORE_PATH=""
ROLLBACK=""
FULL=""
SETUP_WIREGUARD=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --restore|-r) RESTORE_PATH="$2"; shift 2 ;;
        --rollback) ROLLBACK="true"; shift ;;
        --full|-f) FULL="true"; shift ;;
        --setup-wireguard) SETUP_WIREGUARD="true"; shift ;;
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
[ -n "$SETUP_WIREGUARD" ] && echo "   Mode: SETUP-WIREGUARD"
[ -z "$RESTORE_PATH" ] && [ -z "$ROLLBACK" ] && [ -z "$FULL" ] && [ -z "$SETUP_WIREGUARD" ] && echo "   Mode: QUICK"
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
run_ssh "mkdir -p $REMOTE_DIR/dumps $REMOTE_DIR/scripts"

log "Syncing files..."
run_rsync -avz docker-compose.prod.yml .env.prod Caddyfile "$REMOTE:$REMOTE_DIR/"

# Sync scripts directory (including wireguard-clients.conf and backup script)
log "Syncing scripts..."
run_rsync -avz scripts/ "$REMOTE:$REMOTE_DIR/scripts/"
run_ssh "chmod +x $REMOTE_DIR/scripts/*.sh"

# Sync SSH keys to remote server for WireGuard provisioning
log "Syncing SSH keys for WireGuard provisioning..."
run_ssh "mkdir -p /root/.ssh && chmod 700 /root/.ssh"
if [ -f "$HOME/.ssh/id_ed25519" ]; then
    run_rsync -avz "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_ed25519.pub" "$REMOTE:/root/.ssh/"
    run_ssh "chmod 600 /root/.ssh/id_ed25519 && chmod 644 /root/.ssh/id_ed25519.pub"
    log "Ed25519 SSH keys synced ✓"
elif [ -f "$HOME/.ssh/id_rsa" ]; then
    run_rsync -avz "$HOME/.ssh/id_rsa" "$HOME/.ssh/id_rsa.pub" "$REMOTE:/root/.ssh/"
    run_ssh "chmod 600 /root/.ssh/id_rsa && chmod 644 /root/.ssh/id_rsa.pub"
    log "RSA SSH keys synced ✓"
else
    warn "No SSH keys found locally. WireGuard provisioning may fail."
fi

# =============================================================================
# WIREGUARD SETUP (if needed)
# =============================================================================
# Check if WireGuard is already configured
WIREGUARD_CONFIGURED=false
if run_ssh "test -f /etc/wireguard/server_private.key" 2>/dev/null; then
    WIREGUARD_CONFIGURED=true
fi

# Setup WireGuard if:
# 1. Explicitly requested with --setup-wireguard flag, OR
# 2. Not yet configured (first time setup)
if [ -n "$SETUP_WIREGUARD" ] || [ "$WIREGUARD_CONFIGURED" = false ]; then
    if [ "$WIREGUARD_CONFIGURED" = true ]; then
        log "WireGuard already configured, but --setup-wireguard flag set. Reconfiguring..."
    else
        log "WireGuard not configured. Setting up..."
    fi
    
    # Run WireGuard setup script (locally, not on remote)
    log "Running WireGuard setup..."
    if bash "$SCRIPT_DIR/scripts/setup-wireguard.sh"; then
        log "WireGuard setup completed ✓"
    else
        warn "WireGuard setup had issues. Check logs if needed."
    fi
else
    log "WireGuard already configured. Skipping setup. (Use --setup-wireguard to reconfigure)"
fi

# Ensure WireGuard is running (critical for Docker to bind to 10.0.0.1)
log "Checking if WireGuard is running..."
if run_ssh "systemctl is-active --quiet wg-quick@wg0"; then
    log "WireGuard is running ✓"
else
    warn "WireGuard is not running. Starting it now..."
    if run_ssh "systemctl start wg-quick@wg0"; then
        log "WireGuard started ✓"
        sleep 2  # Wait for interface to come up
    else
        error "Failed to start WireGuard. Docker containers need 10.0.0.1 interface. Run: ./deploy.sh --setup-wireguard"
    fi
fi

# =============================================================================
# SETUP DATABASE BACKUPS
# =============================================================================
log "Setting up database backup cronjob..."
run_ssh "mkdir -p /opt/nx-backups"

# Check if cron job already exists
if run_ssh "crontab -l 2>/dev/null | grep -q 'backup_databases.sh'"; then
    log "Backup cronjob already exists ✓"
else
    log "Adding backup cronjob (daily at 4 AM)..."
    run_ssh "(crontab -l 2>/dev/null || true; echo '0 4 * * * /opt/nx-backend/scripts/backup_databases.sh >> /var/log/nx-backup.log 2>&1') | crontab -"
    log "Backup cronjob added ✓"
fi

# =============================================================================
# RESTORE MODE
# =============================================================================
if [ -n "$RESTORE_PATH" ]; then
    [ ! -f "$RESTORE_PATH/postgres_all.sql.gz" ] && error "Postgres backup not found: $RESTORE_PATH/postgres_all.sql.gz"
    [ ! -f "$RESTORE_PATH/mongodb.archive.gz" ] && error "MongoDB backup not found: $RESTORE_PATH/mongodb.archive.gz"
    
    log "Transferring backups..."
    run_rsync -avz --progress "$RESTORE_PATH/postgres_all.sql.gz" "$RESTORE_PATH/mongodb.archive.gz" "$REMOTE:$REMOTE_DIR/dumps/"
    
    log "Stopping services..."
    remote_compose "down -v" 2>/dev/null || true
    
    log "Starting databases..."
    remote_compose "up -d db mongodb"
    sleep 20
    
    log "Restoring PostgreSQL..."
    run_ssh "cd $REMOTE_DIR && gunzip -c dumps/postgres_all.sql.gz | docker exec -i nx-backend-db-1 psql -U $POSTGRES_USER -d $POSTGRES_DB" 2>&1 | tail -5
    log "PostgreSQL restored ✓"
    
    log "Restoring MongoDB..."
    run_ssh "gunzip -c $REMOTE_DIR/dumps/mongodb.archive.gz | docker exec -i nx-backend-mongodb-1 mongorestore --archive --drop --noIndexRestore -u $MONGODB_USERNAME -p $MONGODB_PASSWORD --authenticationDatabase admin" 2>&1 | grep -E "(document|finished|restoring)" | tail -5
    log "MongoDB restored ✓"
    
    log "Starting all services..."
    remote_compose "up -d" 2>/dev/null
    
    echo ""
    echo -e "\033[0;32m════════════════════════════════════════════════\033[0m"
    echo -e "\033[0;32m  ✓ PostgreSQL restored successfully\033[0m"
    echo -e "\033[0;32m  ✓ MongoDB restored successfully\033[0m"
    echo -e "\033[0;32m  ✓ All services started\033[0m"
    echo -e "\033[0;32m════════════════════════════════════════════════\033[0m"
    echo ""
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
