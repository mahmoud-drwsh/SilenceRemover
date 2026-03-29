#!/bin/bash
# MP3 Manager - SSH Deployment Script
# Usage: ./deploy.sh <VPS_IP>
# Example: ./deploy.sh <YOUR_SERVER_IP>

set -e

# Check if IP argument provided
if [ -z "$1" ]; then
    echo "Usage: $0 <VPS_IP>"
    echo "Example: $0 <YOUR_SERVER_IP>"
    exit 1
fi

VPS_IP="$1"
VPS_USER="root"
DEPLOY_PATH="/root/mp3-manager"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Timestamp for logging
get_timestamp() {
    date '+%H:%M:%S'
}

# Print with timestamp
log() {
    echo "[$(get_timestamp)] $1"
}

# Check if required commands exist
if ! command -v rsync &> /dev/null; then
    echo "Error: rsync is not installed"
    exit 1
fi

if ! command -v ssh &> /dev/null; then
    echo "Error: ssh is not installed"
    exit 1
fi

log "=========================================="
log "MP3 Manager Deployment"
log "Target: $VPS_USER@$VPS_IP"
log "Path: $DEPLOY_PATH"
log "=========================================="
log ""

# Test SSH connection
log "Testing SSH connection to $VPS_IP..."
if ! ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$VPS_USER@$VPS_IP" "echo 'SSH OK'" &> /dev/null; then
    log "Error: Cannot connect to $VPS_IP via SSH"
    log "Make sure:"
    log "  - SSH key is configured (ssh-copy-id root@$VPS_IP)"
    log "  - Server is reachable"
    exit 1
fi
log "SSH connection successful ✓"
log ""

# Get and display the current token from VPS
log "Retrieving current authentication token from server..."
TOKEN=$(ssh "$VPS_USER@$VPS_IP" "echo \$MP3_TOKEN" 2>/dev/null || echo "NOT_SET")
if [ "$TOKEN" = "NOT_SET" ] || [ -z "$TOKEN" ]; then
    log "Warning: MP3_TOKEN not set on server"
else
    log "Current MP3_TOKEN: $TOKEN"
fi
log ""

# Analyze local files
log "Analyzing local files..."
cd "$LOCAL_DIR"

# Count files to sync
FILE_COUNT=$(find . -type f \
    -not -path './storage/*' \
    -not -path './__pycache__/*' \
    -not -path './*.pyc' \
    -not -path './.git/*' \
    -not -path './database.db' \
    -not -path './*.log' \
    -not -path './deploy.sh' \
    -not -path './SECURITY_ANALYSIS.md' \
    -not -path './SECURITY_SUMMARY.md' \
    2>/dev/null | wc -l)

log "Found $FILE_COUNT files to sync (excluding storage, cache, logs, etc.)"

# List files that will be synced
log "Files to be deployed:"
rsync -avzn \
    --exclude='storage/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.git/' \
    --exclude='database.db' \
    --exclude='*.log' \
    --exclude='deploy.sh' \
    --exclude='SECURITY_ANALYSIS.md' \
    --exclude='SECURITY_SUMMARY.md' \
    . "$VPS_USER@$VPS_IP:$DEPLOY_PATH" 2>/dev/null | grep -E '^>' | sed 's/^> /  /' | head -20

if [ "$FILE_COUNT" -gt 20 ]; then
    log "  ... and $((FILE_COUNT - 20)) more files"
fi
log ""

# Sync files
log "Syncing files to $DEPLOY_PATH..."
rsync -avz --delete \
    --exclude='storage/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.git/' \
    --exclude='database.db' \
    --exclude='*.log' \
    --exclude='deploy.sh' \
    --exclude='SECURITY_ANALYSIS.md' \
    --exclude='SECURITY_SUMMARY.md' \
    . "$VPS_USER@$VPS_IP:$DEPLOY_PATH"

log "Files synced successfully ✓"
log ""

# Restart service
log "Restarting mp3-manager service..."
if ssh "$VPS_USER@$VPS_IP" "systemctl restart mp3-manager" 2>/dev/null; then
    log "Service restarted ✓"
else
    log "Warning: Could not restart via systemctl, trying direct..."
    # Fallback: kill existing process and start manually
    ssh "$VPS_USER@$VPS_IP" "pkill -f 'python.*app.py' 2>/dev/null; cd $DEPLOY_PATH && nohup python app.py > server.log 2>&1 &"
    log "Service started via direct execution ✓"
fi
log ""

# Health check
log "Performing health check..."
sleep 2

# Check if service is responding
if ssh "$VPS_USER@$VPS_IP" "curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health 2>/dev/null || echo '000'" | grep -q "200"; then
    log "Health check passed ✓"
    HEALTH_STATUS="OK"
elif ssh "$VPS_USER@$VPS_IP" "pgrep -f 'python.*app.py' > /dev/null" 2>/dev/null; then
    log "Process is running (PID: $(ssh $VPS_USER@$VPS_IP "pgrep -f 'python.*app.py'" 2>/dev/null)) ✓"
    HEALTH_STATUS="OK"
else
    log "Warning: Could not verify service health"
    log "Check logs: ssh $VPS_USER@$VPS_IP 'journalctl -u mp3-manager -n 20'"
    HEALTH_STATUS="UNKNOWN"
fi

log ""
log "=========================================="
log "Deployment Summary"
log "=========================================="
log "Target: $VPS_IP"
log "Files deployed: $FILE_COUNT"
log "Health status: $HEALTH_STATUS"
log "=========================================="
log ""
log "Access your MP3 Manager:"
log "  Web Interface: https://$VPS_IP/interface/<TOKEN>"
log ""
log "Useful commands:"
log "  View logs: ssh $VPS_USER@$VPS_IP 'journalctl -u mp3-manager -f'"
log "  Restart:   ssh $VPS_USER@$VPS_IP 'systemctl restart mp3-manager'"
log ""

exit 0
