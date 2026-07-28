#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root/remote-js"

if [ ! -f .env ]; then
  echo "remote-js/.env is required on the VPS. Create it from remote-js/.env.example and keep it out of Git."
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose=(docker-compose)
else
  echo "Docker Compose is required: install Docker with the compose plugin or docker-compose."
  exit 1
fi

echo "== Build and start Media Manager =="
"${compose[@]}" up -d --build

echo
echo "== Compose status =="
"${compose[@]}" ps

echo
echo "== Health check =="
health_url="${MEDIA_MANAGER_HEALTH_URL:-http://127.0.0.1:${PORT:-8080}/healthz}"
for attempt in $(seq 1 30); do
  if curl -fsS "$health_url"; then
    echo
    echo "Media Manager is healthy: $health_url"
    exit 0
  fi
  sleep 2
  printf 'Waiting for health check (%s/30)\n' "$attempt"
done

echo "Media Manager did not become healthy: $health_url"
"${compose[@]}" logs --tail=120 media-manager
exit 1
