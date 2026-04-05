#!/bin/bash
# Deploy MP3 Manager to VPS (non-destructive)
# Usage: ./deploy.sh [user@host]
# Example: ./deploy.sh root@my-server.com

set -e

VPS="${1}"

if [ -z "$VPS" ]; then
    echo "Usage: ./deploy.sh [user@host]"
    echo "Example: ./deploy.sh root@my-server.com"
    exit 1
fi

echo "=== Deploying MP3 Manager to $VPS ==="
echo "(Preserves existing token and database)"
echo ""

# 1. Copy app, templates, and translations
echo "[1/2] Copying app.py, templates/, and translations.json..."
scp ./remote/app.py "$VPS:/var/lib/mp3-manager/app.py"
scp -r ./remote/templates "$VPS:/var/lib/mp3-manager/"
scp ./remote/translations.json "$VPS:/var/lib/mp3-manager/translations.json"

# 2. Restart service
echo "[2/2] Restarting service..."
ssh "$VPS" "systemctl restart mp3-manager && sleep 1 && systemctl is-active mp3-manager"

echo ""
echo "✓ Deployed successfully"
