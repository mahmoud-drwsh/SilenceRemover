#!/bin/bash
# Script to batch process videos from VIDS folder

# Set paths
VIDS_DIR="/Users/mahmoud/Desktop/VIDS"
OUTPUT_DIR="/Users/mahmoud/Desktop/trimmed"

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if VIDS directory exists
if [ ! -d "$VIDS_DIR" ]; then
    echo "Error: VIDS directory not found at $VIDS_DIR"
    exit 1
fi

# Run the batch processor
echo "Processing videos from: $VIDS_DIR"
echo "Output directory: $OUTPUT_DIR"
echo ""

uv run python process_directory.py "$VIDS_DIR" --output-dir "$OUTPUT_DIR" --target-length 145

