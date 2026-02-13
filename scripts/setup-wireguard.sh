#!/bin/bash
set -euo pipefail

# =============================================================================
# WireGuard Server Setup - Multi-Client Support
# =============================================================================
# Usage: 
#   ./setup-wireguard.sh              # Setup/update with clients from config
#   ./setup-wireguard.sh --list       # List configured clients
#
# NOTE: To add new clients, use the API endpoint:
#   POST /api/provisioning/register
#   Headers: X-API-Key: <your-api-key>
#   Body: {"machine_id": "...", "public_key": "...", "client_name": "..."}
#
# The API endpoint automatically applies changes after registration.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env.prod"
CLIENTS_FILE="$SCRIPT_DIR/wireguard-clients.conf"

# Load .env.prod
if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
else
    echo "ERROR: .env.prod not found at $ENV_FILE"
    exit 1
fi

: "${REMOTE_USER:?REMOTE_USER not set}"
: "${REMOTE_HOST:?REMOTE_HOST not set}"

REMOTE="$REMOTE_USER@$REMOTE_HOST"

# Colors
log() { echo -e "\033[0;32m[✓]\033[0m $1"; }
warn() { echo -e "\033[1;33m[!]\033[0m $1"; }
error() { echo -e "\033[0;31m[✗]\033[0m $1"; exit 1; }

# SSH helper
run_ssh() { ssh -o StrictHostKeyChecking=accept-new "$REMOTE" "$@"; }

# List clients
list_clients() {
    echo "Configured WireGuard Clients:"
    echo "────────────────────────────────────────"
    printf "%-20s %-20s %-40s %s\n" "MACHINE_ID" "NAME" "PUBLIC KEY" "IP"
    echo "────────────────────────────────────────"
    while read -r line; do
        [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
        # Support both old (3 fields) and new (4 fields) formats
        field_count=$(echo "$line" | awk -F'|' '{print NF}')
        if [ "$field_count" -eq 4 ]; then
            machine_id=$(echo "$line" | cut -d'|' -f1)
            name=$(echo "$line" | cut -d'|' -f2)
            pubkey=$(echo "$line" | cut -d'|' -f3)
            ip=$(echo "$line" | cut -d'|' -f4)
        else
            # Old format: NAME|PUBKEY|IP
            machine_id="unknown"
        name=$(echo "$line" | cut -d'|' -f1)
        pubkey=$(echo "$line" | cut -d'|' -f2)
        ip=$(echo "$line" | cut -d'|' -f3)
        fi
        printf "%-20s %-20s %-40s 10.0.0.%s\n" "$machine_id" "$name" "${pubkey:0:35}..." "$ip"
    done < "$CLIENTS_FILE"
    echo "────────────────────────────────────────"
}

# Generate peers config
generate_peers() {
    local peers=""
    while read -r line; do
        [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
        # Support both old (3 fields) and new (4 fields) formats
        field_count=$(echo "$line" | awk -F'|' '{print NF}')
        if [ "$field_count" -eq 4 ]; then
            name=$(echo "$line" | cut -d'|' -f2)
            pubkey=$(echo "$line" | cut -d'|' -f3)
            ip=$(echo "$line" | cut -d'|' -f4)
        else
            # Old format: NAME|PUBKEY|IP
        name=$(echo "$line" | cut -d'|' -f1)
        pubkey=$(echo "$line" | cut -d'|' -f2)
        ip=$(echo "$line" | cut -d'|' -f3)
        fi
        peers+="
# $name
[Peer]
PublicKey = $pubkey
AllowedIPs = 10.0.0.$ip/32
"
    done < "$CLIENTS_FILE"
    echo "$peers"
}

# Parse args
case "${1:-}" in
    --list)
        list_clients
        exit 0
        ;;
esac

# Check clients file
[ ! -f "$CLIENTS_FILE" ] && error "No clients configured. Add clients via API endpoint POST /api/provisioning/register"

# Count actual clients (non-comment, non-empty lines)
CLIENT_COUNT=$(grep -v '^#' "$CLIENTS_FILE" | grep -v '^$' | wc -l)

# Handle zero clients case
if [ "$CLIENT_COUNT" -eq 0 ]; then
    warn "No clients found in $CLIENTS_FILE"
    warn "WireGuard can technically run without peers, but it's not useful."
    warn "Stopping WireGuard service to prevent issues..."
    run_ssh "systemctl stop wg-quick@wg0" 2>/dev/null || true
    run_ssh "systemctl disable wg-quick@wg0" 2>/dev/null || true
    warn "Add clients via API endpoint: POST /api/provisioning/register"
    warn "Then run this script again to start WireGuard."
    exit 0
fi

echo "================================================"
echo "   WireGuard Setup -> $REMOTE_HOST"
echo "   Clients: $CLIENT_COUNT"
echo "================================================"

# Check if WireGuard is installed
if ! run_ssh "command -v wg" &>/dev/null; then
    log "Installing WireGuard..."
    run_ssh "apt update -qq && apt install -y wireguard" >/dev/null
fi

# Check if keys exist
if ! run_ssh "test -f /etc/wireguard/server_private.key" &>/dev/null; then
    log "Generating server keys..."
    run_ssh "mkdir -p /etc/wireguard && wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key && chmod 600 /etc/wireguard/server_private.key"
fi

SERVER_PUBKEY=$(run_ssh "cat /etc/wireguard/server_public.key")
SERVER_PRIVKEY=$(run_ssh "cat /etc/wireguard/server_private.key")
PEERS=$(generate_peers)

# Verify we have peers before proceeding
if [ -z "$PEERS" ] || [ "$(echo "$PEERS" | grep -c '\[Peer\]')" -eq 0 ]; then
    error "No valid peers generated. This should not happen. Check $CLIENTS_FILE format."
fi

log "Configuring WireGuard with $CLIENT_COUNT client(s)..."

# Create config with actual private key (not command substitution)
run_ssh "cat > /etc/wireguard/wg0.conf << 'WGEOF'
[Interface]
PrivateKey = $SERVER_PRIVKEY
Address = 10.0.0.1/24
ListenPort = 51820
$PEERS
WGEOF
chmod 600 /etc/wireguard/wg0.conf"

log "Restarting WireGuard..."
# Stop first to ensure clean restart (handles any previous broken state)
run_ssh "systemctl stop wg-quick@wg0" 2>/dev/null || true
sleep 1
run_ssh "systemctl enable wg-quick@wg0 >/dev/null 2>&1 || true"

# Start WireGuard
if run_ssh "systemctl start wg-quick@wg0"; then
    log "WireGuard started successfully"
else
    error "Failed to start WireGuard. Check logs: systemctl status wg-quick@wg0"
fi

log "Verifying..."
run_ssh "wg show wg0"

echo ""
echo "════════════════════════════════════════════════"
echo -e "\033[0;32m  ✓ WireGuard configured with $CLIENT_COUNT client(s)\033[0m"
echo "════════════════════════════════════════════════"
echo ""
echo "Server Public Key: $SERVER_PUBKEY"
echo "Server Endpoint:   $REMOTE_HOST:51820"
echo ""
echo "Clients can connect to:"
echo "  PostgreSQL: 10.0.0.1:5432"
echo "  MongoDB:    10.0.0.1:27017"
echo ""
echo "Commands:"
echo "  List clients:  $0 --list"
echo ""
echo "To add new clients:"
echo "  Use API: POST /api/provisioning/register"
echo ""
