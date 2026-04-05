#!/bin/bash
# Deploy MP3 Manager SPA to server
# Usage: ./deploy-spa.sh root@your-server.com

set -e

SERVER="${1}"

if [ -z "$SERVER" ]; then
    echo "Usage: ./deploy-spa.sh root@your-server.com"
    exit 1
fi

echo "=== Deploying MP3 Manager SPA to $SERVER ==="

echo "[1/4] Copying backend..."
scp remote/app_api.py "$SERVER:/var/lib/mp3-manager/"

echo "[2/4] Copying static files..."
scp -r remote/static/* "$SERVER:/var/lib/mp3-manager/static/"

echo "[3/4] Restarting services..."
ssh "$SERVER" "systemctl restart mp3-manager && sleep 1 && systemctl is-active mp3-manager"

echo "[4/4] Reloading Caddy..."
ssh "$SERVER" "caddy reload 2>/dev/null || caddy start"

echo ""
echo "✓ Deployed successfully!"
echo "Get your token from server: ssh $SERVER 'cat /var/lib/mp3-manager/.env | grep MP3_TOKEN'"
