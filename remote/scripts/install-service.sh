#!/bin/bash
# Install Media Manager and File Browser as systemd services
# Usage: sudo ./install-service.sh

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Error: Run with sudo"
    exit 1
fi

cd "$(dirname "$0")"
REPO_DIR="$(cd .. && pwd)"

echo "Installing media-manager.service..."
cp "$REPO_DIR/media-manager.service" /etc/systemd/system/media-manager.service

echo "Installing filebrowser.service..."
FB_BINARY=""
if [ -x /usr/local/bin/filebrowser ]; then
    FB_BINARY="/usr/local/bin/filebrowser"
elif command -v filebrowser >/dev/null 2>&1; then
    FB_BINARY="$(command -v filebrowser)"
fi

if [ -z "$FB_BINARY" ]; then
    echo "filebrowser binary not found. Installing File Browser automatically..."
    FB_TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "$FB_TMP_DIR"' EXIT
    FB_ARCHIVE_URL=""
    if command -v jq >/dev/null 2>&1; then
        FB_LATEST_TAG="$(curl -fsSL "https://api.github.com/repos/filebrowser/filebrowser/releases/latest" | jq -r '.tag_name' 2>/dev/null || true)"
        if [ -n "$FB_LATEST_TAG" ] && [ "$FB_LATEST_TAG" != "null" ]; then
            FB_ASSET_NAME="$(curl -fsSL "https://api.github.com/repos/filebrowser/filebrowser/releases/latest" | jq -r '.assets[] | select(.name | endswith("linux-amd64-filebrowser.tar.gz")) | .name' 2>/dev/null || true)"
            if [ -n "$FB_ASSET_NAME" ] && [ "$FB_ASSET_NAME" != "null" ]; then
                FB_ARCHIVE_URL="https://github.com/filebrowser/filebrowser/releases/download/$FB_LATEST_TAG/$FB_ASSET_NAME"
            fi
        fi
    fi
    if [ -z "$FB_ARCHIVE_URL" ]; then
        FB_ARCHIVE_URL="https://github.com/filebrowser/filebrowser/releases/latest/download/linux-amd64-filebrowser.tar.gz"
    fi
    if curl -fsSL "$FB_ARCHIVE_URL" -o "$FB_TMP_DIR/filebrowser.tar.gz"; then
        tar -xzf "$FB_TMP_DIR/filebrowser.tar.gz" -C "$FB_TMP_DIR" filebrowser
        install -m 0755 "$FB_TMP_DIR/filebrowser" /usr/local/bin/filebrowser
        FB_BINARY="/usr/local/bin/filebrowser"
    else
        echo "Failed to download File Browser. You can install it manually."
        echo "  - download from https://github.com/filebrowser/filebrowser/releases/latest/download/linux-amd64-filebrowser.tar.gz"
        echo "  - extract and place binary at /usr/local/bin/filebrowser"
    fi
fi

if [ -n "$FB_BINARY" ] && [ -x "$FB_BINARY" ]; then
    if [ "$FB_BINARY" != "/usr/local/bin/filebrowser" ]; then
        ln -sf "$FB_BINARY" /usr/local/bin/filebrowser
    fi
    cp "$REPO_DIR/filebrowser.service" /etc/systemd/system/filebrowser.service
    echo "File Browser service file installed."
else
    echo "filebrowser binary not found. To enable it, install File Browser manually:"
    echo "  - download from https://github.com/filebrowser/filebrowser/releases"
    echo "  - place binary at /usr/local/bin/filebrowser"
    echo "Skipping File Browser service install until binary is available."
fi

systemctl daemon-reload
systemctl enable media-manager
if [ -f /etc/systemd/system/filebrowser.service ]; then
    systemctl enable filebrowser
fi

echo "Service installed."
echo ""
echo "Commands:"
echo "  sudo systemctl start media-manager   # Start now"
echo "  sudo systemctl status media-manager  # Check status"
echo "  sudo systemctl restart media-manager # Restart"
echo "  sudo journalctl -u media-manager -f   # View logs"
if [ -f /etc/systemd/system/filebrowser.service ]; then
    echo "  sudo systemctl start filebrowser     # Start filebrowser now"
    echo "  sudo systemctl status filebrowser    # Check filebrowser status"
    echo "  sudo systemctl restart filebrowser   # Restart filebrowser"
    echo "  sudo journalctl -u filebrowser -f     # View filebrowser logs"
fi
echo ""
echo "To start the service now, run:"
echo "  sudo systemctl start media-manager"
