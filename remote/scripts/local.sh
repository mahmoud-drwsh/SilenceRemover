#!/bin/bash
# Run Media Manager locally for testing
# Usage: ./local.sh

cd "$(dirname "$0")/.."

# Check for libmagic (required by python-magic)
if ! command -v brew &>/dev/null; then
    echo "Error: Homebrew required. Install from https://brew.sh"
    exit 1
fi

if ! brew list libmagic &>/dev/null; then
    echo "Installing libmagic..."
    brew install libmagic
fi

# Use fixed token for development
export MEDIA_TOKEN="${MEDIA_TOKEN:-123}"
echo "Token: $MEDIA_TOKEN"

# Create venv if missing
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Install deps if needed
if ! venv/bin/python -c "import fastapi, magic" 2>/dev/null; then
    echo "Installing dependencies..."
    venv/bin/pip install -r requirements.txt
fi

# Data directory (local, not /var/lib)
export DATA_DIR="./data"

# Clean old database if it exists (dev mode - fresh start each time)
if [ -f "$DATA_DIR/database.db" ]; then
    echo "Removing old database..."
    rm -f "$DATA_DIR/database.db"
fi

mkdir -p "$DATA_DIR/storage"

echo ""
echo "Starting server..."
echo "URL: http://localhost:8080/$MEDIA_TOKEN/test-project/"
echo ""

venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080 --reload
