#!/bin/bash
# Generate test media files using ffmpeg
# Usage: ./generate-test-media.sh [count]

cd "$(dirname "$0")/.."

COUNT="${1:-3}"
OUTPUT_DIR="./test-media"

# Check for ffmpeg
if ! command -v ffmpeg &>/dev/null; then
    echo "Error: ffmpeg required. Install with: brew install ffmpeg"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "Generating $COUNT test audio files..."

for i in $(seq 1 "$COUNT"); do
    DURATION=$((10 + RANDOM % 50))  # 10-60 seconds
    FILENAME=$(printf "%03d" $i)_test_audio_${DURATION}s.mp3
    
    echo "  - $FILENAME (${DURATION}s)"
    
    ffmpeg -f lavfi -i "sine=frequency=$((200 + i * 100)):duration=$DURATION" \
        -ar 44100 -ac 2 -b:a 128k \
        -y "$OUTPUT_DIR/$FILENAME" 2>/dev/null
done

echo ""
echo "Generating $COUNT test video files..."

for i in $(seq 1 "$COUNT"); do
    DURATION=$((5 + RANDOM % 20))  # 5-25 seconds
    FILENAME=$(printf "%03d" $i)_test_video_${DURATION}s.mp4
    
    echo "  - $FILENAME (${DURATION}s)"
    
    # Generate a test video with color bars and sine wave audio
    ffmpeg -f lavfi -i testsrc=duration=$DURATION:size=640x480:rate=30 \
        -f lavfi -i sine=frequency=$((300 + i * 50)):duration=$DURATION \
        -pix_fmt yuv420p -c:v libx264 -c:a aac -b:a 128k \
        -y "$OUTPUT_DIR/$FILENAME" 2>/dev/null
done

echo ""
echo "Created $(($COUNT * 2)) test files in: $OUTPUT_DIR/"
echo ""
echo "Upload examples:"
echo "  # Audio"
echo "  curl -X POST http://localhost:8080/\$MEDIA_TOKEN/test-project/upload \\"
echo "    -F \"id=audio001\" \\"
echo "    -F \"title=Test Audio 1\" \\"
echo "    -F \"file=@$OUTPUT_DIR/001_test_audio_*.mp3\""
echo ""
echo "  # Video"
echo "  curl -X POST http://localhost:8080/\$MEDIA_TOKEN/test-project/upload \\"
echo "    -F \"id=video001\" \\"
echo "    -F \"title=Test Video 1\" \\"
echo "    -F \"file=@$OUTPUT_DIR/001_test_video_*.mp4\""
