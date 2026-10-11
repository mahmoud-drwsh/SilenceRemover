#!/usr/bin/env bash
# Run the isolated integration flows on a fresh database with synthetic media.
# The stack uses no production data: no database dump and no .local-test.
# Each flow gets its own Compose project, because the flows share project
# names and would change the results of the other flows. Each stack has an
# internal network, publishes no host ports, and is removed with "down -v".
#
# Usage: tests/integration/run_isolated_fresh.sh [flow ...]
#   flow: originals | canonical-card | source-processing | client-contract |
#         views-perf | browser
#   No flow runs originals, canonical-card, source-processing, and
#   client-contract. views-perf times the video views of a large project
#   (#51); run it by name.
#   client-contract runs the real Python pipeline client
#   (packages/sr_media_manager) against the app.
#   browser runs the Playwright tests in tests/browser; run it by name. Set
#   BROWSER_TESTS to run only some tests (unittest names).
# Set ISOLATED_MINIO=dockerhub to use the minio/minio images of the base file
# instead of the Chainguard MinIO override.
# Set SRFRESH_TAG to a unique value (for example the worktree name) so that
# parallel runs do not replace the srfresh-* images of each other.
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
files+=(-f docker-compose.isolated.browser.yml)
echo "=== image tag: ${SRFRESH_TAG:-local}"

# Make sure that the merged configuration has no .local-test mount and no
# published port.
if docker compose -p fresh-check "${files[@]}" config | grep -nE 'local-test|published:|backups'; then
  echo "error: the merged Compose configuration uses local data or publishes a port." >&2
  exit 2
fi

flows=("$@")
if [ ${#flows[@]} -eq 0 ]; then
  flows=(originals canonical-card source-processing client-contract)
fi

current_project=""
cleanup() {
  if [ -n "$current_project" ]; then
    docker compose -p "$current_project" "${files[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    # Remove the images that have the project name (for example the Chainguard
    # minio-init image). Keep the shared srfresh-*:${SRFRESH_TAG} images.
    docker image ls -q --filter "reference=${current_project}-*" | xargs -r docker rmi -f >/dev/null 2>&1 || true
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
    views-perf) "${compose[@]}" run --rm --no-deps -e VIEWS_PERF_MAX_MS="${VIEWS_PERF_MAX_MS:-300}" \
      canonical-card-integration python /tests/video_views_perf.py ;;
    source-processing) "${compose[@]}" run --rm --no-deps source-processing-integration ;;
    client-contract) "${compose[@]}" run --rm --no-deps client-contract-integration ;;
    browser)
      # BROWSER_TESTS selects tests, for example "test_video_views.PagingTest".
      local tests=()
      [ -n "${BROWSER_TESTS:-}" ] && tests=(python -m unittest -v ${BROWSER_TESTS})
      "${compose[@]}" run --rm --no-deps --build browser-integration "${tests[@]}" ;;
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
