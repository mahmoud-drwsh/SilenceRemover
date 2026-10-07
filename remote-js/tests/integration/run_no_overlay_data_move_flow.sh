#!/usr/bin/env bash
# Run the no-overlay data move test in the isolated Compose stack.
# The stack has its own Compose project name and an internal network, so it
# does not publish ports. The stack is removed at the end.
set -euo pipefail

remote_js="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$remote_js"

compose_project="${NO_OVERLAY_TEST_COMPOSE_PROJECT:-spec44t3}"
compose=(docker compose -p "$compose_project" -f docker-compose.isolated.yml)
# Set NO_OVERLAY_TEST_COMPOSE_OVERRIDE=docker-compose.isolated.chainguard-minio.yml
# when the Docker Hub MinIO images are not available.
if [ -n "${NO_OVERLAY_TEST_COMPOSE_OVERRIDE:-}" ]; then
  compose+=(-f "$NO_OVERLAY_TEST_COMPOSE_OVERRIDE")
fi

cleanup() { "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

"${compose[@]}" up -d --build app
"${compose[@]}" exec -T app mkdir -p /app/tests/integration
"${compose[@]}" cp tests/integration/no_overlay_data_move_flow.ts app:/app/tests/integration/no_overlay_data_move_flow.ts
"${compose[@]}" exec -T app bun run tests/integration/no_overlay_data_move_flow.ts
