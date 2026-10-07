#!/usr/bin/env bash
# Run the isolated integration flows on a fresh database with synthetic media.
# The stack uses no production data: no database dump and no .local-test.
# Each flow gets its own Compose project, because the flows share project
# names and would change the results of the other flows. Each stack has an
# internal network, publishes no host ports, and is removed with "down -v".
#
# Usage: tests/integration/run_isolated_fresh.sh [flow ...]
#   flow: originals | canonical-card | source-processing | data-move
#   No flow runs all four flows.
# Set ISOLATED_MINIO=dockerhub to use the minio/minio images of the base file
# instead of the Chainguard MinIO override.
set -uo pipefail

remote_js="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
repo="$(cd "$remote_js/.." && pwd)"
cd "$remote_js"

# The source-processing flow mounts the repository root. Refuse to run when
# the repository has local production data in it.
if [ -e "$repo/.local-test" ]; then
  echo "error: $repo/.local-test exists. Run this script from a checkout without it." >&2
  exit 2
fi

files=(-f docker-compose.isolated.yml)
if [ "${ISOLATED_MINIO:-chainguard}" != "dockerhub" ]; then
  files+=(-f docker-compose.isolated.chainguard-minio.yml)
fi
files+=(-f docker-compose.isolated.fresh.yml)

# Make sure that the merged configuration has no .local-test mount and no
# published port.
if docker compose -p fresh-check "${files[@]}" config | grep -nE 'local-test|published:|backups'; then
  echo "error: the merged Compose configuration uses local data or publishes a port." >&2
  exit 2
fi

flows=("$@")
[ ${#flows[@]} -eq 0 ] && flows=(originals canonical-card source-processing data-move)

current_project=""
cleanup() {
  if [ -n "$current_project" ]; then
    docker compose -p "$current_project" "${files[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

run_flow() {
  local flow="$1"
  local compose=(docker compose -p "$current_project" "${files[@]}")
  case "$flow" in
    originals) "${compose[@]}" run --rm --no-deps integration ;;
    canonical-card) "${compose[@]}" run --rm --no-deps canonical-card-integration ;;
    source-processing) "${compose[@]}" run --rm --no-deps source-processing-integration ;;
    data-move)
      "${compose[@]}" exec -T app mkdir -p /app/tests/integration &&
        "${compose[@]}" cp tests/integration/no_overlay_data_move_flow.ts app:/app/tests/integration/no_overlay_data_move_flow.ts &&
        "${compose[@]}" exec -T app bun run tests/integration/no_overlay_data_move_flow.ts ;;
    *) echo "unknown flow: $flow" >&2; return 2 ;;
  esac
}

declare -A result
status=0
for flow in "${flows[@]}"; do
  current_project="srfresh-${flow}-$$"
  echo "=== $flow (project $current_project)"
  # "up" runs the one-time seed services. "run --no-deps" does not run them
  # again, so wait here until the fixture service has made the media.
  if docker compose -p "$current_project" "${files[@]}" up -d --build app fixture &&
     [ "$(docker wait "$(docker compose -p "$current_project" "${files[@]}" ps -aq fixture)")" = "0" ] &&
     run_flow "$flow"; then
    result[$flow]=pass
  else
    result[$flow]=FAIL
    status=1
    docker compose -p "$current_project" "${files[@]}" logs --no-color --tail 40 app >&2 || true
  fi
  cleanup
  current_project=""
done

echo "=== results"
for flow in "${flows[@]}"; do echo "$flow: ${result[$flow]}"; done
exit "$status"
