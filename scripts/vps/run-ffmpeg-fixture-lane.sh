#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

fixture_dir="${1:-tests/fixtures}"

echo "== Generate required fixtures =="
uv run python tests/generate_fixtures.py "$fixture_dir"

echo
echo "== Validate fixture manifest =="
uv run python tests/generate_fixtures.py --check "$fixture_dir"

echo
echo "== Project FFmpeg API smoke =="
uv run python tests/ffmpeg_api_smoke.py

echo
echo "== Direct libx265 fixture smoke =="
tmp_base="$(mktemp -t silenceremover-vps-x265-XXXXXX)"
tmp_output="${tmp_base}.mp4"
trap 'rm -f "$tmp_base" "$tmp_output"' EXIT

ffmpeg \
  -hide_banner \
  -v error \
  -f lavfi \
  -i testsrc=duration=1:size=320x240:rate=25 \
  -frames:v 25 \
  -c:v libx265 \
  -crf 24 \
  -preset slow \
  -pix_fmt yuv420p \
  -tag:v hvc1 \
  -movflags +faststart \
  -y \
  "$tmp_output"

ffprobe -hide_banner -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$tmp_output"

echo
echo "FFmpeg fixture lane passed with software HEVC."
