#!/bin/bash
# Complete server setup for MP3 Manager SPA
# Run as root on fresh Ubuntu/Debian server

set -e

echo "=== MP3 Manager Server Setup ==="
echo ""

# Configuration
APP_DIR="/var/lib/mp3-manager"
UPLOAD_DIR="/var/www/uploads"
STATIC_DIR="$APP_DIR/static"
DB_PATH="$APP_DIR/db.sqlite"
SERVICE_NAME="mp3-manager"

# Generate secure token
MP3_TOKEN=$(openssl rand -hex 32)
echo "Generated token: $MP3_TOKEN"
echo "SAVE THIS TOKEN! You'll need it for the MP3_MANAGER_URL"
echo ""

# 1. Install dependencies
echo "[1/7] Installing dependencies..."
apt-get update
apt-get install -y python3 python3-pip sqlite3 curl

# Install Caddy
echo "[2/7] Installing Caddy..."
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

# 2. Install Python packages
echo "[3/7] Installing Python packages..."
pip3 install flask mutagen werkzeug

# 3. Create directories
echo "[4/7] Creating directories..."
mkdir -p "$APP_DIR"
mkdir -p "$UPLOAD_DIR"
mkdir -p "$STATIC_DIR"
chown -R root:root "$APP_DIR"
chmod 755 "$UPLOAD_DIR"

# 4. Create environment file
echo "[5/7] Creating environment file..."
cat > "$APP_DIR/.env" << EOF
MP3_TOKEN=$MP3_TOKEN
UPLOAD_DIR=$UPLOAD_DIR
DB_PATH=$DB_PATH
STATIC_DIR=$STATIC_DIR
PORT=8080
EOF
chmod 600 "$APP_DIR/.env"

# 5. Create systemd service
echo "[6/7] Creating systemd service..."
cat > "/etc/systemd/system/$SERVICE_NAME.service" << EOF
[Unit]
Description=MP3 Manager API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=/usr/bin/python3 $APP_DIR/app_api.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Copy files to server:"
echo "   scp remote/app_api.py root@YOUR_SERVER:$APP_DIR/"
echo "   scp -r remote/static/* root@YOUR_SERVER:$STATIC_DIR/"
echo ""
echo "2. Update Caddyfile with your domain"
echo "   Edit /etc/caddy/Caddyfile"
echo ""
echo "3. Start services:"
echo "   systemctl start $SERVICE_NAME"
echo "   caddy reload"
echo ""
echo "Your token: $MP3_TOKEN"
echo "Your URL will be: https://YOUR_DOMAIN/$MP3_TOKEN/arabic-lessons/"
echo ""
