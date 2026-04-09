#!/bin/bash
# Start Media Manager on VPS
# Usage: ./start.sh

cd "$(dirname "$0")/.."

# Load token from .env if exists
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Generate and save token if not set
if [ -z "$MEDIA_TOKEN" ]; then
    MEDIA_TOKEN=$(openssl rand -hex 32)
    echo "MEDIA_TOKEN=$MEDIA_TOKEN" > .env
    chmod 600 .env
    echo "Generated new token and saved to .env"
fi

echo ""
echo "========================================"
echo "MEDIA_TOKEN: $MEDIA_TOKEN"
echo "========================================"
echo ""

# Ensure data directory exists
export DATA_DIR="${DATA_DIR:-/var/lib/media-manager}"
mkdir -p "$DATA_DIR/storage"

# Create venv if missing
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Install deps if needed
if ! venv/bin/python -c "import flask, magic" 2>/dev/null; then
    echo "Installing dependencies..."
    venv/bin/pip install -r requirements.txt
fi

echo "Starting Media Manager..."
echo "Data directory: $DATA_DIR"
echo ""

venv/bin/python app.py
