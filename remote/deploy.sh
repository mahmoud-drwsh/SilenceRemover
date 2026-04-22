#!/bin/bash
# Deploy Media Manager to server and auto-install service
# Usage: ./deploy.sh [--sync-only] user@server
#
# IMPORTANT SAFETY GUARANTEE:
#   This script NEVER deletes files on the remote server - ever.
#   Even if you delete files locally, they will NOT be deleted on the server.
#   Remote file deletions must be done manually via SSH.
#
# Options:
#   --sync-only    Sync files without restarting the service (safe deploy)
#                  Use this to update code and restart manually later.

set -e

# Parse arguments
SYNC_ONLY=false
SERVER=""

for arg in "$@"; do
    case $arg in
        --sync-only)
            SYNC_ONLY=true
            shift
            ;;
        -*)
            echo "Unknown option: $arg"
            echo "Usage: ./deploy.sh [--sync-only] root@myserver.com"
            exit 1
            ;;
        *)
            SERVER="$arg"
            ;;
    esac
done

REMOTE_DIR="/var/lib/media-manager"

if [ -z "$SERVER" ]; then
    echo "Usage: ./deploy.sh [--sync-only] root@myserver.com"
    echo ""
    echo "Options:"
    echo "  --sync-only    Sync files without restarting the service"
    echo "                 (restart manually with: systemctl restart media-manager)"
    echo ""
    echo "SAFETY: This script NEVER deletes remote files."
    echo "        Local deletions will NOT propagate to the server."
    exit 1
fi

echo "════════════════════════════════════════════════════════════════"
echo "  SAFETY MODE: NO FILES WILL BE DELETED ON REMOTE SERVER"
echo "  Local deletions will NOT propagate - manual cleanup required"
echo "════════════════════════════════════════════════════════════════"
echo ""

if [ "$SYNC_ONLY" = true ]; then
    echo "MODE: Sync-only (no service restart)"
    echo ""
fi

echo "Deploying to $SERVER..."

# 1. Ensure remote directory exists and sync files
ssh "$SERVER" "mkdir -p $REMOTE_DIR"

echo ""
echo "Syncing files with DELETION PROTECTION..."
echo "  Default rsync behavior: NO files deleted on remote"
echo ""

# Sync - rsync defaults to NOT deleting files (safe for older versions)
# --ignore-errors       Continue even if some files fail (safer)
# -v                    Verbose to show what's happening
rsync -avz \
    --ignore-errors \
    --exclude='.git' \
    --exclude='.DS_Store' \
    --exclude='.env' \
    --exclude='data/' \
    --exclude='storage/' \
    --exclude='venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='database.db' \
    ./ "$SERVER:$REMOTE_DIR/"

echo ""
echo "✓ Sync complete - NO files were deleted on remote server"
echo ""

# 2. Install dependencies (safe to do while running)
ssh "$SERVER" "
    cd $REMOTE_DIR
    
    # Create venv if missing
    if [ ! -d 'venv' ]; then
        echo 'Creating virtual environment...'
        python3 -m venv venv
    fi
    
    # Ensure .env exists with required tokens
    if [ ! -f '.env' ]; then
        echo 'Creating .env with tokens...'
        MEDIA_TOKEN=\$(python3 -c 'import secrets; print(secrets.token_hex(16))' 2>/dev/null || head /dev/urandom | tr -dc a-z0-9 | head -c 32)
        ADMIN_TOKEN=\$(python3 -c 'import secrets; print(secrets.token_hex(16))' 2>/dev/null || head /dev/urandom | tr -dc a-z0-9 | head -c 32)
        echo 'MEDIA_TOKEN='\$MEDIA_TOKEN > .env
        echo 'ADMIN_TOKEN='\$ADMIN_TOKEN >> .env
        echo 'Generated MEDIA_TOKEN: '\$MEDIA_TOKEN
        echo 'Generated ADMIN_TOKEN: '\$ADMIN_TOKEN
    else
        # Ensure ADMIN_TOKEN exists in existing .env (for upgrades)
        if ! grep -q '^ADMIN_TOKEN=' .env; then
            echo 'Adding ADMIN_TOKEN to existing .env...'
            ADMIN_TOKEN=\$(python3 -c 'import secrets; print(secrets.token_hex(16))' 2>/dev/null || head /dev/urandom | tr -dc a-z0-9 | head -c 32)
            echo 'ADMIN_TOKEN='\$ADMIN_TOKEN >> .env
            echo 'Generated ADMIN_TOKEN: '\$ADMIN_TOKEN
        fi
    fi
    
    # Install dependencies (can be done while service is running)
    echo 'Installing/updating dependencies...'
    venv/bin/pip install -r requirements.txt >/dev/null 2>&1 && echo 'Dependencies up to date'
    
    # Install/update systemd services (media-manager + file-browser sidecar)
    echo 'Installing/updating systemd services...'
    ./scripts/install-service.sh
"

# 3. Restart service (unless --sync-only)
if [ "$SYNC_ONLY" = true ]; then
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "  SYNC-ONLY DEPLOY COMPLETE"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "Files synced to: $REMOTE_DIR"
    echo "Remote deletions: NONE (safety preserved)"
    echo "Media Manager status:   $(ssh "$SERVER" 'systemctl is-active media-manager 2>/dev/null || echo "unknown"')"
    echo "File Browser status:    $(ssh "$SERVER" 'systemctl is-active filebrowser 2>/dev/null || echo "not installed"')"
    echo ""
    echo "The service is still running the OLD code."
    echo "New code is synced but NOT active."
    echo ""
    echo "To activate new code, restart manually:"
    echo "  ssh $SERVER 'systemctl restart media-manager'"
    echo "  (if installed) ssh $SERVER 'systemctl restart filebrowser'"
    echo ""
    exit 0
fi

# Full deploy with restart
# Ensure both services have latest unit files and restart where available
ssh "$SERVER" "systemctl daemon-reload && systemctl restart media-manager && (systemctl list-unit-files filebrowser.service >/dev/null 2>&1 && systemctl restart filebrowser || true)"
echo "✓ Service(s) restarted with new code"

# Wait a moment for service to initialize and get token
sleep 2

echo ""
echo "========================================"
echo "Media Manager deployed successfully!"
echo "========================================"
echo ""
echo "SAFETY REMINDER: No files were deleted on the remote server."
echo "If you need to clean up old files, do it manually via SSH."
echo ""

# Get and display the tokens
MEDIA_TOKEN=$(ssh "$SERVER" "cat $REMOTE_DIR/.env 2>/dev/null | grep MEDIA_TOKEN | cut -d= -f2" || echo "")
ADMIN_TOKEN=$(ssh "$SERVER" "cat $REMOTE_DIR/.env 2>/dev/null | grep ADMIN_TOKEN | cut -d= -f2" || echo "")

if [ -n "$MEDIA_TOKEN" ]; then
    echo "Your MEDIA_TOKEN:"
    echo "  $MEDIA_TOKEN"
    echo ""
    echo "Project URLs:"
    echo "  https://$SERVER/projects/\$MEDIA_TOKEN/<project>/"
    echo "  https://$SERVER/projects/\$MEDIA_TOKEN/test-project/"
    echo ""
else
    echo "MEDIA_TOKEN not yet generated. First run may be initializing."
    echo "Check with: ssh $SERVER 'cat $REMOTE_DIR/.env'"
fi

if [ -n "$ADMIN_TOKEN" ]; then
    echo "Your ADMIN_TOKEN:"
    echo "  $ADMIN_TOKEN"
    echo ""
    echo "Admin Dashboard:"
    echo "  https://$SERVER/admin/\$ADMIN_TOKEN/"
    echo ""
    echo "File Browser:"
    echo "  https://$SERVER/admin/\$ADMIN_TOKEN/files/"
    echo ""
fi

echo "Service status:"
echo "  ssh $SERVER 'systemctl status media-manager'"
echo "  (if installed) ssh $SERVER 'systemctl status filebrowser'"
