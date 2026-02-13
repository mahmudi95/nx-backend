#!/bin/bash
set -euo pipefail

# =============================================================================
# Build & Push Docker Image to GHCR
# Then deploy to servers using deploy.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env.prod for IMAGE_NAME and credentials
if [ -f "$SCRIPT_DIR/.env.prod" ]; then
    source "$SCRIPT_DIR/.env.prod"
else
    echo "ERROR: .env.prod not found"
    exit 1
fi

: "${GITHUB_USER:?GITHUB_USER not set}"
: "${GITHUB_TOKEN:?GITHUB_TOKEN not set}"
: "${IMAGE_NAME:?IMAGE_NAME not set}"

cd "$SCRIPT_DIR"

# 1. Build image
echo "🔨 Building image..."
docker build -t "$IMAGE_NAME:latest" .

# 2. Login to GHCR
echo "🔑 Logging into GHCR..."
echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin

# 3. Push to registry
echo "📤 Pushing to GHCR..."
docker push "$IMAGE_NAME:latest"

# 4. Deploy to servers
HOSTS=("46.225.30.213")  # Add more IPs here as needed

for host in "${HOSTS[@]}"; do
    echo "🚀 Deploying to $host..."
    DEPLOY_HOST="$host" ./deploy.sh --full --migrate
done

echo "✅ Build, push, and deploy complete to all hosts!"