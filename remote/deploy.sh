#!/bin/bash
# Deploy Media Manager to server and auto-install services.
# Usage: ./deploy.sh [--sync-only] [--caddy-domain DOMAIN] root@server
#
# IMPORTANT SAFETY GUARANTEE:
#   This script NEVER deletes files on the remote server - ever.
#   Even if files are deleted locally, they will NOT be deleted on the server.
#   Remote file deletions must be done manually via SSH.
#
# Options:
#   --sync-only         Sync files without restarting services (safe deploy).
#   --caddy-domain      Replace YOUR_DOMAIN in local Caddyfile before validation/upload.
#   Caddyfile is always synced to /etc/caddy/Caddyfile (when caddy exists) and Caddy is restarted.

set -e

# Parse arguments
SYNC_ONLY=false
CADDY_DOMAIN="${CADDY_DOMAIN:-}"
NON_INTERACTIVE=false
SERVER=""
DEPLOY_HOST=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sync-only)
            SYNC_ONLY=true
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
        --non-interactive)
            NON_INTERACTIVE=true
            shift
            ;;
        -*)
            echo "Unknown option: $1"
            echo "Usage: ./deploy.sh [--sync-only] [--caddy-domain DOMAIN] [--non-interactive] root@myserver.com"
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
    echo "Usage: ./deploy.sh [--sync-only] [--caddy-domain DOMAIN] [--non-interactive] root@myserver.com"
    echo ""
    echo "Options:"
    echo "  --sync-only         Sync files without restarting services"
    echo "  --caddy-domain      Replace YOUR_DOMAIN in Caddyfile before validation/upload"
    echo "  --non-interactive   Do not prompt for env updates; only generate missing tokens"
    echo "  Caddyfile is always synced (if present) and Caddy is restarted when available."
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
if [ -n "$DEPLOY_HOST" ] && [[ "$DEPLOY_HOST" == *:* ]]; then
    DEPLOY_HOST="${DEPLOY_HOST%:*}"
fi

echo "Deploying to $SERVER..."

generate_token() {
    python3 -c 'import secrets; print(secrets.token_hex(16))' 2>/dev/null || LC_ALL=C tr -dc a-z0-9 </dev/urandom | head -c 32
}

mask_value() {
    local value="$1"
    if [ -z "$value" ]; then
        printf "<unset>"
    elif [ "${#value}" -le 8 ]; then
        printf "********"
    else
        printf "%s...%s" "${value:0:4}" "${value: -4}"
    fi
}

url_encode() {
    python3 - "$1" <<'PY'
import sys
from urllib.parse import quote

print(quote(sys.argv[1], safe=""))
PY
}

env_get() {
    local key="$1"
    awk -F= -v k="$key" '$1 == k {sub(/^[^=]*=/, ""); print; exit}' "$ENV_SNAPSHOT" 2>/dev/null || true
}

env_set_local() {
    local key="$1"
    local value="$2"
    if grep -q "^$key=" "$ENV_UPDATE_FILE" 2>/dev/null; then
        local escaped_value
        escaped_value="$(printf '%s' "$value" | sed 's/[\/&]/\\&/g')"
        sed -i.bak "s/^$key=.*/$key=$escaped_value/" "$ENV_UPDATE_FILE"
        rm -f "$ENV_UPDATE_FILE.bak"
    else
        printf '%s=%s\n' "$key" "$value" >> "$ENV_UPDATE_FILE"
    fi
}

env_pending_or_existing() {
    local key="$1"
    local pending
    pending="$(awk -F= -v k="$key" '$1 == k {sub(/^[^=]*=/, ""); print; exit}' "$ENV_UPDATE_FILE" 2>/dev/null || true)"
    if [ -n "$pending" ]; then
        printf "%s" "$pending"
    else
        env_get "$key"
    fi
}

prompt_env_value() {
    local key="$1"
    local label="$2"
    local default_value="$3"
    local secret="${4:-false}"
    local existing
    local prompt
    local answer

    existing="$(env_get "$key")"
    if [ "$NON_INTERACTIVE" = true ] || [ ! -t 0 ]; then
        if [ -z "$existing" ] && [ -n "$default_value" ]; then
            env_set_local "$key" "$default_value"
        fi
        return
    fi

    if [ -n "$existing" ]; then
        if [ "$secret" = true ]; then
            prompt="$label [$key] exists ($(mask_value "$existing")). Press Enter to keep, type a new value to update: "
        else
            prompt="$label [$key] exists ($existing). Press Enter to keep, type a new value to update: "
        fi
        if [ "$secret" = true ]; then
            read -r -s -p "$prompt" answer
            echo ""
        else
            read -r -p "$prompt" answer
        fi
        if [ -n "$answer" ]; then
            env_set_local "$key" "$answer"
        fi
    else
        if [ -n "$default_value" ]; then
            if [ "$secret" = true ]; then
                read -r -s -p "$label [$key] is missing. Press Enter for default, or type a value: " answer
                echo ""
            else
                read -r -p "$label [$key] is missing. Press Enter for '$default_value', or type a value: " answer
            fi
            env_set_local "$key" "${answer:-$default_value}"
        else
            while true; do
                if [ "$secret" = true ]; then
                    read -r -s -p "$label [$key] is missing. Enter value: " answer
                    echo ""
                else
                    read -r -p "$label [$key] is missing. Enter value: " answer
                fi
                if [ -n "$answer" ]; then
                    env_set_local "$key" "$answer"
                    break
                fi
            done
        fi
    fi
}

write_env_updates_file() {
    chmod 600 "$ENV_UPDATE_FILE"
}

# 1. Ensure remote directory exists and sync files
ssh "$SERVER" "mkdir -p $REMOTE_DIR"

# 1a. Bootstrap or update remote environment configuration.
ENV_SNAPSHOT="$(mktemp)"
ENV_UPDATE_FILE="$(mktemp)"
trap 'rm -f "$ENV_SNAPSHOT" "$ENV_UPDATE_FILE"' EXIT
chmod 600 "$ENV_UPDATE_FILE"

ssh "$SERVER" "cat '$REMOTE_DIR/.env' 2>/dev/null || true" > "$ENV_SNAPSHOT"

if [ -z "$(env_get MEDIA_TOKEN)" ]; then
    env_set_local MEDIA_TOKEN "$(generate_token)"
fi
if [ -z "$(env_get ADMIN_TOKEN)" ]; then
    env_set_local ADMIN_TOKEN "$(generate_token)"
fi

echo ""
echo "Configuring remote service environment..."
if [ "$NON_INTERACTIVE" = true ] || [ ! -t 0 ]; then
    echo "  Non-interactive mode: preserving existing values and filling safe defaults."
else
    echo "  Existing values are kept by default. Secrets are masked in prompts."
fi

env_set_local STORAGE_BACKEND "s3"
env_set_local DATABASE_BACKEND "supabase"

prompt_env_value S3_ENDPOINT_URL "S3 endpoint URL" "https://eu2.contabostorage.com"
prompt_env_value S3_BUCKET "S3 bucket name" "media-manager"
prompt_env_value S3_ACCESS_KEY "S3 access key" "" true
prompt_env_value S3_SECRET_KEY "S3 secret key" "" true
prompt_env_value S3_REGION "S3 region" "eu2"

prompt_env_value SUPABASE_DB_HOST "Supabase database host" "aws-1-eu-central-2.pooler.supabase.com"
prompt_env_value SUPABASE_DB_PORT "Supabase database port" "6543"
prompt_env_value SUPABASE_DB_NAME "Supabase database name" "postgres"
prompt_env_value SUPABASE_DB_USER "Supabase database user" "postgres.xzgdlobtuagircpnjmho"
prompt_env_value SUPABASE_DB_PASSWORD "Supabase database password" "" true

SUPABASE_DB_HOST_EFFECTIVE="$(env_pending_or_existing SUPABASE_DB_HOST)"
SUPABASE_DB_PORT_EFFECTIVE="$(env_pending_or_existing SUPABASE_DB_PORT)"
SUPABASE_DB_NAME_EFFECTIVE="$(env_pending_or_existing SUPABASE_DB_NAME)"
SUPABASE_DB_USER_EFFECTIVE="$(env_pending_or_existing SUPABASE_DB_USER)"
SUPABASE_DB_PASSWORD_EFFECTIVE="$(env_pending_or_existing SUPABASE_DB_PASSWORD)"

if [ -n "$SUPABASE_DB_HOST_EFFECTIVE" ] && [ -n "$SUPABASE_DB_PORT_EFFECTIVE" ] && [ -n "$SUPABASE_DB_NAME_EFFECTIVE" ] && [ -n "$SUPABASE_DB_USER_EFFECTIVE" ] && [ -n "$SUPABASE_DB_PASSWORD_EFFECTIVE" ]; then
    SUPABASE_DB_USER_ENCODED="$(url_encode "$SUPABASE_DB_USER_EFFECTIVE")"
    SUPABASE_DB_PASSWORD_ENCODED="$(url_encode "$SUPABASE_DB_PASSWORD_EFFECTIVE")"
    env_set_local SUPABASE_DATABASE_URL "postgresql://$SUPABASE_DB_USER_ENCODED:$SUPABASE_DB_PASSWORD_ENCODED@$SUPABASE_DB_HOST_EFFECTIVE:$SUPABASE_DB_PORT_EFFECTIVE/$SUPABASE_DB_NAME_EFFECTIVE"
fi

write_env_updates_file
if [ -s "$ENV_UPDATE_FILE" ]; then
    REMOTE_ENV_UPDATE="/tmp/media-manager-env-update.$$"
    scp -q "$ENV_UPDATE_FILE" "$SERVER:$REMOTE_ENV_UPDATE"
    ssh "$SERVER" "REMOTE_DIR='$REMOTE_DIR' REMOTE_ENV_UPDATE='$REMOTE_ENV_UPDATE' bash -s" <<'REMOTE_ENV'
set -e
ENV_FILE="$REMOTE_DIR/.env"
TMP_FILE="$ENV_FILE.tmp"
mkdir -p "$REMOTE_DIR"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"
cp "$ENV_FILE" "$TMP_FILE"
while IFS='=' read -r key value; do
    [ -n "$key" ] || continue
    if grep -q "^$key=" "$TMP_FILE"; then
        escaped_value="$(printf '%s' "$value" | sed 's/[\/&]/\\&/g')"
        sed -i "s/^$key=.*/$key=$escaped_value/" "$TMP_FILE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$TMP_FILE"
    fi
done < "$REMOTE_ENV_UPDATE"
mv "$TMP_FILE" "$ENV_FILE"
chmod 600 "$ENV_FILE"
rm -f "$REMOTE_ENV_UPDATE"
REMOTE_ENV
    echo "✓ Remote .env updated"
else
    echo "✓ Remote .env unchanged"
fi

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
    --exclude='venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
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

# 3. Sync Caddyfile and restart Caddy (non-destructive)
echo ""
echo "Checking Caddy configuration..."
ssh "$SERVER" "CADDY_DOMAIN='$CADDY_DOMAIN' DEPLOY_HOST='$DEPLOY_HOST' REMOTE_DIR='$REMOTE_DIR' bash -s" <<'REMOTE_CMD'
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
    if [ -z "$CADDY_DOMAIN" ] && [ -f /etc/caddy/Caddyfile ]; then
        CADDY_DOMAIN="$(awk 'BEGIN{found=0} $1 !~ /^#/ && $1 !~ /^$/ && $2 == \"{\" {print $1; found=1; exit} END{if(!found) exit 1}' /etc/caddy/Caddyfile 2>/dev/null || true)"
    fi
    if [ -z "$CADDY_DOMAIN" ] && [ -n "$DEPLOY_HOST" ]; then
        CADDY_DOMAIN="$DEPLOY_HOST"
    fi
    if [ -z "$CADDY_DOMAIN" ]; then
        echo 'Caddyfile still contains YOUR_DOMAIN placeholder and no domain could be determined.'
        echo 'Set --caddy-domain (or export CADDY_DOMAIN), or remove placeholder from remote/Caddyfile.'
        [ -f "$TMP_FILE" ] && rm -f "$TMP_FILE"
        exit 0
    fi
    sed "s/YOUR_DOMAIN/$CADDY_DOMAIN/g" "$SRC_FILE" > "$TMP_FILE"
    SRC_FILE="$TMP_FILE"
fi

if [ -f /etc/caddy/Caddyfile ] && cmp -s "$SRC_FILE" /etc/caddy/Caddyfile; then
    echo 'Caddyfile unchanged; skip caddy sync.'
    [ -f "$TMP_FILE" ] && rm -f "$TMP_FILE"
    if [ "$SRC_FILE" != "$REMOTE_DIR/Caddyfile" ] && [ -f "$SRC_FILE" ]; then
        cp "$SRC_FILE" "$REMOTE_DIR/Caddyfile"
    fi
    exit 0
fi

if ! caddy validate --config "$SRC_FILE" >/dev/null 2>&1; then
    echo 'Caddyfile validation failed. Remote Caddy config was not changed.'
    [ -f "$TMP_FILE" ] && rm -f "$TMP_FILE"
    exit 0
fi

mkdir -p /etc/caddy
cp "$SRC_FILE" /etc/caddy/Caddyfile
cp "$SRC_FILE" "$REMOTE_DIR/Caddyfile"
echo 'Caddyfile synced and validated.'

if command -v systemctl >/dev/null 2>&1; then
    if systemctl list-unit-files caddy.service >/dev/null 2>&1; then
        systemctl restart caddy
    else
        systemctl restart caddy || true
        if ! systemctl is-active --quiet caddy; then
            echo 'Caddy service is not active after restart. You may need to run: systemctl start caddy'
        fi
    fi
fi

[ -f "$TMP_FILE" ] && rm -f "$TMP_FILE"
REMOTE_CMD

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
    echo "Caddy status:          $(ssh "$SERVER" 'systemctl is-active caddy 2>/dev/null || echo \"not installed\"')"
    echo ""
    echo "The service is still running the old code."
    echo "New code is synced but NOT active."
    echo ""
    echo "To activate new code, restart manually:"
    echo "  ssh $SERVER 'systemctl restart media-manager'"
    echo "  ssh $SERVER 'systemctl restart caddy'"
    echo ""
    exit 0
fi

# Full deploy with restart
# Restart app, then Caddy so proxy and admin routes use current code.
ssh "$SERVER" "systemctl daemon-reload && \
    systemctl restart media-manager && \
    (systemctl list-unit-files caddy.service >/dev/null 2>&1 && systemctl restart caddy || true)"
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
fi

echo "Service status:"
echo "  ssh $SERVER 'systemctl status media-manager'"
echo "  (if installed) ssh $SERVER 'systemctl status caddy'"
echo "  Caddy config: $REMOTE_DIR/Caddyfile -> /etc/caddy/Caddyfile"
