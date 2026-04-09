#!/bin/bash
# Deploy Media Manager to server and auto-install service
# Usage: ./deploy.sh user@server

set -e

SERVER="${1:-}"
REMOTE_DIR="/var/lib/media-manager"

if [ -z "$SERVER" ]; then
    echo "Usage: ./deploy.sh root@myserver.com"
    exit 1
fi

echo "Deploying to $SERVER..."

# 1. Ensure remote directory exists and sync files
ssh "$SERVER" "mkdir -p $REMOTE_DIR"

rsync -avz --delete \
    --exclude='.git' \
    --exclude='.DS_Store' \
    --exclude='.env' \
    --exclude='data/' \
    --exclude='venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    ./ "$SERVER:$REMOTE_DIR/"

echo "✓ Files synced"

# 2. Install dependencies and service
ssh "$SERVER" "
    cd $REMOTE_DIR
    
    # Create venv if missing
    if [ ! -d 'venv' ]; then
        echo 'Creating virtual environment...'
        python3 -m venv venv
    fi
    
    # Ensure .env exists with MEDIA_TOKEN
    if [ ! -f '.env' ]; then
        echo 'Creating .env with MEDIA_TOKEN...'
        TOKEN=$(openssl rand -hex 16 2>/dev/null || cat /dev/urandom | tr -dc 'a-z0-9' | head -c 32)
        echo "MEDIA_TOKEN=$TOKEN" > .env
        echo "Generated token: $TOKEN"
    fi
    
    # Install dependencies
    echo 'Installing dependencies...'
    venv/bin/pip install -r requirements.txt
    
    # Install systemd service if not already installed
    if [ ! -f /etc/systemd/system/media-manager.service ]; then
        echo 'Installing systemd service...'
        ./scripts/install-service.sh
    fi
"

# 3. Start/restart the service
ssh "$SERVER" "systemctl daemon-reload && systemctl restart media-manager"
echo "✓ Service restarted"

# 4. Wait a moment for service to initialize and get token
sleep 2

echo ""
echo "========================================"
echo "Media Manager deployed successfully!"
echo "========================================"
echo ""

# Get and display the token
TOKEN=$(ssh "$SERVER" "cat $REMOTE_DIR/.env 2>/dev/null | grep MEDIA_TOKEN | cut -d= -f2" || echo "")

if [ -n "$TOKEN" ]; then
    echo "Your token:"
    echo ""
    echo "  $TOKEN"
    echo ""
    echo "Access URLs:"
    echo "  https://$SERVER/\$TOKEN/<project>/"
    echo "  https://$SERVER/\$TOKEN/test-project/"
else
    echo "Token not yet generated. First run may be initializing."
    echo "Check with: ssh $SERVER 'cat $REMOTE_DIR/.env'"
fi

echo ""
echo "Service status: ssh $SERVER 'systemctl status media-manager'"
