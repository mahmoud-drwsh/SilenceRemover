#!/bin/bash
# Install Media Manager as a systemd service
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

systemctl daemon-reload
systemctl enable media-manager

echo "Service installed."
echo ""
echo "Commands:"
echo "  sudo systemctl start media-manager   # Start now"
echo "  sudo systemctl status media-manager  # Check status"
echo "  sudo systemctl restart media-manager # Restart"
echo "  sudo journalctl -u media-manager -f   # View logs"
echo ""
echo "To start the service now, run:"
echo "  sudo systemctl start media-manager"
