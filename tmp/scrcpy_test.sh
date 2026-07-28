#!/usr/bin/env bash
set -euo pipefail

LOCAL_PORT="${LOCAL_PORT:-15555}"
REMOTE_HOST="${REMOTE_HOST:-ubuntu@devbox}"
REMOTE_ADB_HOST="${REMOTE_ADB_HOST:-127.0.0.1}"
REMOTE_ADB_PORT="${REMOTE_ADB_PORT:-5555}"
DEVICE="127.0.0.1:${LOCAL_PORT}"

adb disconnect "${DEVICE}" >/dev/null 2>&1 || true
adb kill-server >/dev/null 2>&1 || true

if command -v lsof >/dev/null 2>&1; then
  existing_pids="$(lsof -tiTCP:"${LOCAL_PORT}" -sTCP:LISTEN || true)"
  if [[ -n "${existing_pids}" ]]; then
    kill ${existing_pids} || true
  fi
fi

ssh -fN -L "${LOCAL_PORT}:${REMOTE_ADB_HOST}:${REMOTE_ADB_PORT}" "${REMOTE_HOST}"

adb start-server >/dev/null
adb connect "${DEVICE}"
adb devices

scrcpy \
  -s "${DEVICE}" \
  --force-adb-forward \
  --no-audio \
  --max-size 1024 \
  --video-bit-rate 2M \
  --max-fps 30
