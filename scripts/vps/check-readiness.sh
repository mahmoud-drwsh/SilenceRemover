#!/usr/bin/env bash
set -euo pipefail

echo "== System =="
uname -a

echo
echo "== Required tools =="
missing=0
for tool in bun uv python3 ffmpeg ffprobe git docker; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '[OK] %s -> %s\n' "$tool" "$(command -v "$tool")"
  else
    printf '[MISSING] %s\n' "$tool"
    missing=1
  fi
done

if [ "$missing" -ne 0 ]; then
  echo "One or more required tools are missing."
  exit 1
fi

echo
echo "== Versions =="
bun --version
uv --version
python3 --version
ffmpeg -hide_banner -version | sed -n '1p'
ffprobe -hide_banner -version | sed -n '1p'
git --version
docker --version

echo
echo "== HEVC encoder listing =="
ffmpeg -hide_banner -encoders | grep -E '(libx265|hevc_qsv|hevc_vaapi|hevc_amf)' || true

probe_encoder() {
  local codec="$1"
  shift

  if ffmpeg \
    -hide_banner \
    -v error \
    -f lavfi \
    -i testsrc=duration=1:size=320x240:rate=25 \
    -frames:v 25 \
    -c:v "$codec" \
    "$@" \
    -pix_fmt yuv420p \
    -f null \
    - >/tmp/silenceremover-"$codec"-probe.log 2>&1; then
    printf '[OK] %s probe passed\n' "$codec"
    return 0
  fi

  printf '[FAIL] %s probe failed\n' "$codec"
  sed -n '1,80p' /tmp/silenceremover-"$codec"-probe.log
  return 1
}

echo
echo "== Required software encode probe =="
probe_encoder libx265 -crf 24 -preset slow

echo
echo "== Advisory hardware encode probes =="
if [ -e /dev/dri/renderD128 ]; then
  if ffmpeg -hide_banner -v error -vaapi_device /dev/dri/renderD128 \
    -f lavfi -i testsrc2=duration=1:size=320x240:rate=25 \
    -vf format=nv12,hwupload -frames:v 25 -c:v hevc_vaapi -global_quality 20 \
    -f null - >/tmp/silenceremover-hevc_vaapi-probe.log 2>&1; then
    echo '[OK] hevc_vaapi iGPU probe passed'
  else
    echo '[FAIL] hevc_vaapi iGPU probe failed'
    sed -n '1,80p' /tmp/silenceremover-hevc_vaapi-probe.log
  fi
else
  echo '[SKIP] hevc_vaapi: /dev/dri/renderD128 is unavailable'
fi
probe_encoder hevc_qsv -global_quality 20 -preset slow || true
probe_encoder hevc_amf -qp_i 22 -qp_p 22 -quality quality || true

echo
echo "VPS readiness passed. Hardware probe failures above are non-blocking here."
