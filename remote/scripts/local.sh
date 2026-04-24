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
export ADMIN_TOKEN="${ADMIN_TOKEN:-admin123}"
echo "Media token: $MEDIA_TOKEN"
echo "Admin token: $ADMIN_TOKEN"

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

missing=()
for key in SUPABASE_DATABASE_URL S3_ENDPOINT_URL S3_BUCKET S3_ACCESS_KEY S3_SECRET_KEY S3_REGION; do
    if [ -z "${!key:-}" ]; then
        missing+=("$key")
    fi
done

if [ "${#missing[@]}" -gt 0 ]; then
    echo "Error: local development now requires Supabase and S3 environment variables:"
    printf '  %s\n' "${missing[@]}"
    exit 1
fi

mkdir -p "$DATA_DIR"

echo ""
echo "Starting server..."
echo "Project URL: http://localhost:8080/projects/$MEDIA_TOKEN/test-project/"
echo "Admin URL: http://localhost:8080/admin/$ADMIN_TOKEN/"
echo ""

venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080 --reload
