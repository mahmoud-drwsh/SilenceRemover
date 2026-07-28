#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

echo "== Python tests =="
uv run pytest

echo
echo "== remote-js Bun tests =="
(
  cd remote-js
  bun test
  bun run typecheck
)

if [ -d pipeline-js ]; then
  echo
  echo "== pipeline-js Bun tests =="
  (
    cd pipeline-js
    bun test
    bun --bun tsc --noEmit
  )
else
  echo
  echo "pipeline-js/ not present; skipping future Bun pipeline lane."
fi

echo
echo "Code lane passed."
