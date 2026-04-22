#!/bin/bash
# Deploy Media Manager to server and auto-install services.
# Usage: ./deploy.sh [--sync-only] [--sync-caddy] [--caddy-domain DOMAIN] [--skip-caddy-reload] root@server
#
# IMPORTANT SAFETY GUARANTEE:
#   This script NEVER deletes files on the remote server - ever.
#   Even if files are deleted locally, they will NOT be deleted on the server.
#   Remote file deletions must be done manually via SSH.
#
# Options:
#   --sync-only         Sync files without restarting services (safe deploy).
#   --sync-caddy        Sync local Caddyfile -> /etc/caddy/Caddyfile and validate before reload.
#   --caddy-domain      Replace YOUR_DOMAIN in local Caddyfile before validation/upload.
#   --skip-caddy-reload Skip caddy reload/restart even when not in --sync-only mode.

set -e

# Parse arguments
SYNC_ONLY=false
SYNC_CADDY=false
SKIP_CADDY_RELOAD=false
CADDY_DOMAIN="${CADDY_DOMAIN:-}"
SERVER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sync-only)
            SYNC_ONLY=true
            shift
            ;;
        --sync-caddy)
            SYNC_CADDY=true
            shift
            ;;
        --skip-caddy-reload)
            SKIP_CADDY_RELOAD=true
            shift
            ;;
        --caddy-domain)
            if [[ $# -lt 2 || "$2" == --* ]]; then
                echo "Usage: --caddy-domain requires a DOMAIN value"
                exit 1
            fi
            CADDY_DOMAIN="$2"
            shift 2
            ;;
        -*)
            echo "Unknown option: $1"
            echo "Usage: ./deploy.sh [--sync-only] [--sync-caddy] [--caddy-domain DOMAIN] [--skip-caddy-reload] root@myserver.com"
            exit 1
            ;;
        *)
            SERVER="$1"
            shift
            ;;
    esac
done

REMOTE_DIR="/var/lib/media-manager"

if [ -z "$SERVER" ]; then
    echo "Usage: ./deploy.sh [--sync-only] [--sync-caddy] [--caddy-domain DOMAIN] [--skip-caddy-reload] root@myserver.com"
    echo ""
    echo "Options:"
    echo "  --sync-only         Sync files without restarting services"
    echo "  --sync-caddy        Sync local Caddyfile to /etc/caddy/Caddyfile and validate"
    echo "  --caddy-domain      Replace YOUR_DOMAIN in Caddyfile before validation/upload"
    echo "  --skip-caddy-reload Skip caddy reload/restart"
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

DEPLOY_HOST="${SERVER#*@}"
if [ "$DEPLOY_HOST" = "$SERVER" ]; then
    DEPLOY_HOST="$SERVER"
fi

echo "Deploying to $SERVER..."

# 1. Ensure remote directory exists and sync files
ssh "$SERVER" "mkdir -p $REMOTE_DIR"

echo ""
echo "Syncing files with DELETION PROTECTION..."
echo "  Default rsync behavior: NO files deleted on remote"
echo ""

# Sync - rsync defaults to NOT deleting files (safe for older versions)
# --ignore-errors  Continue even if some files fail (safer)
# -a and -v         Archive + verbose
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

# 2. Install dependencies and services (safe while service is running)
ssh "$SERVER" "
    cd '$REMOTE_DIR'

    if [ ! -d 'venv' ]; then
        echo 'Creating virtual environment...'
        python3 -m venv venv
    fi

    if [ ! -f '.env' ]; then
        echo 'Creating .env with generated tokens...'
        MEDIA_TOKEN=\$(python3 -c 'import secrets; print(secrets.token_hex(16))' 2>/dev/null || head /dev/urandom | tr -dc a-z0-9 | head -c 32)
        ADMIN_TOKEN=\$(python3 -c 'import secrets; print(secrets.token_hex(16))' 2>/dev/null || head /dev/urandom | tr -dc a-z0-9 | head -c 32)
        echo 'MEDIA_TOKEN='\$MEDIA_TOKEN > .env
        echo 'ADMIN_TOKEN='\$ADMIN_TOKEN >> .env
        echo 'Generated MEDIA_TOKEN: '\$MEDIA_TOKEN
        echo 'Generated ADMIN_TOKEN: '\$ADMIN_TOKEN
    elif ! grep -q '^ADMIN_TOKEN=' .env; then
        echo 'Adding ADMIN_TOKEN to existing .env...'
        ADMIN_TOKEN=\$(python3 -c 'import secrets; print(secrets.token_hex(16))' 2>/dev/null || head /dev/urandom | tr -dc a-z0-9 | head -c 32)
        echo 'ADMIN_TOKEN='\$ADMIN_TOKEN >> .env
        echo 'Generated ADMIN_TOKEN: '\$ADMIN_TOKEN
    fi

    echo 'Installing/updating dependencies...'
    venv/bin/pip install -r requirements.txt >/dev/null 2>&1 && echo 'Dependencies up to date'

    echo 'Installing/updating systemd services...'
    ./scripts/install-service.sh
"

# 3. Optional Caddy sync/reload (non-destructive)
if [ "$SYNC_CADDY" = true ]; then
    echo ""
    echo "Checking Caddy configuration..."
    ssh "$SERVER" "CADDY_DOMAIN='$CADDY_DOMAIN' SYNC_ONLY='$SYNC_ONLY' SKIP_CADDY_RELOAD='$SKIP_CADDY_RELOAD' REMOTE_DIR='$REMOTE_DIR' bash -s" <<'REMOTE_CMD'
set -e

if ! command -v caddy >/dev/null 2>&1; then
    echo 'caddy binary not found on remote. Skipping caddy sync/reload.'
    exit 0
fi

if [ ! -f "$REMOTE_DIR/Caddyfile" ]; then
    echo 'No local Caddyfile was synced to remote. Skipping caddy sync.'
    exit 0
fi

SRC_FILE="$REMOTE_DIR/Caddyfile"
TMP_FILE='/tmp/Caddyfile.deploy'
if grep -q 'YOUR_DOMAIN' "$SRC_FILE"; then
    if [ -n "$CADDY_DOMAIN" ]; then
        sed "s/YOUR_DOMAIN/$CADDY_DOMAIN/g" "$SRC_FILE" > "$TMP_FILE"
        SRC_FILE="$TMP_FILE"
    else
        echo 'Caddyfile still contains YOUR_DOMAIN placeholder. Set --caddy-domain and retry, or edit manually.'
        exit 0
    fi
fi

if [ -f /etc/caddy/Caddyfile ] && cmp -s "$SRC_FILE" /etc/caddy/Caddyfile; then
    echo 'Caddyfile unchanged; skip caddy sync.'
    [ -f "$TMP_FILE" ] && rm -f "$TMP_FILE"
    exit 0
fi

if ! caddy validate --config "$SRC_FILE" >/dev/null 2>&1; then
    echo 'Caddyfile validation failed. Remote Caddy config was not changed.'
    [ -f "$TMP_FILE" ] && rm -f "$TMP_FILE"
    exit 0
fi

mkdir -p /etc/caddy
cp "$SRC_FILE" /etc/caddy/Caddyfile
echo 'Caddyfile synced and validated.'

if [ "${SKIP_CADDY_RELOAD}" != "true" ] && [ "${SYNC_ONLY}" != "true" ]; then
    if command -v systemctl >/dev/null 2>&1; then
        if systemctl is-active --quiet caddy; then
            systemctl reload caddy || echo 'Caddy reload failed. You may need to restart caddy manually.'
        else
            echo 'Caddy is not active. Start with: systemctl start caddy'
        fi
    fi
fi

[ -f "$TMP_FILE" ] && rm -f "$TMP_FILE"
REMOTE_CMD
fi

# 4. Restart services (unless --sync-only)
if [ "$SYNC_ONLY" = true ]; then
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "  SYNC-ONLY DEPLOY COMPLETE"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "Files synced to: $REMOTE_DIR"
    echo "Remote deletions: NONE (safety preserved)"
    echo "Media Manager status:   $(ssh "$SERVER" 'systemctl is-active media-manager 2>/dev/null || echo \"unknown\"')"
    echo "File Browser status:    $(ssh "$SERVER" 'systemctl is-active filebrowser 2>/dev/null || echo \"not installed\"')"
    if [ "$SYNC_CADDY" = true ]; then
        echo "Caddy status:          $(ssh "$SERVER" 'systemctl is-active caddy 2>/dev/null || echo \"not installed\"')"
    fi
    echo ""
    echo "The service is still running the old code."
    echo "New code is synced but NOT active."
    echo ""
    echo "To activate new code, restart manually:"
    echo "  ssh $SERVER 'systemctl restart media-manager'"
    echo "  (if installed) ssh $SERVER 'systemctl restart filebrowser'"
    echo "  (if installed) ssh $SERVER 'systemctl reload caddy'"
    echo ""
    exit 0
fi

# Full deploy with restart
ssh "$SERVER" "systemctl daemon-reload && systemctl restart media-manager && (systemctl list-unit-files filebrowser.service >/dev/null 2>&1 && systemctl restart filebrowser || true)"
echo "✓ Service(s) restarted with new code"

if [ "$SYNC_CADDY" = true ] && [ "$SKIP_CADDY_RELOAD" != true ]; then
    ssh "$SERVER" "if command -v caddy >/dev/null 2>&1; then if systemctl is-active --quiet caddy; then systemctl reload caddy || true; fi; fi"
fi

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
    echo "  https://$DEPLOY_HOST/projects/$MEDIA_TOKEN/<project>/"
    echo "  https://$DEPLOY_HOST/projects/$MEDIA_TOKEN/test-project/"
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
    echo "  https://$DEPLOY_HOST/admin/$ADMIN_TOKEN/"
    echo ""
    echo "File Browser:"
    echo "  https://$DEPLOY_HOST/admin/$ADMIN_TOKEN/files/"
    echo ""
fi

echo "Service status:"
echo "  ssh $SERVER 'systemctl status media-manager'"
echo "  (if installed) ssh $SERVER 'systemctl status filebrowser'"
if [ "$SYNC_CADDY" = true ]; then
    echo "  (if installed) ssh $SERVER 'systemctl status caddy'"
    echo "  Caddy config: $REMOTE_DIR/Caddyfile -> /etc/caddy/Caddyfile"
fi
