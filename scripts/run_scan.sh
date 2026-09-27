#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then
  exec uv run opportunity-miner scan "$@"
fi
# Fallback if uv is not installed
export PYTHONPATH="${PYTHONPATH:-}:src"
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
exec opportunity-miner scan "$@"
