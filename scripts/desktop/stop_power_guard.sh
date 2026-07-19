#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
PID_FILE="$ROOT_DIR/.power_guard.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "Power guard is not running"
  exit 0
fi

pid=$(cat "$PID_FILE" 2>/dev/null || true)
if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid" || true
  echo "Power guard stopped (PID: $pid)"
else
  echo "Power guard PID file existed but process was not running"
fi

rm -f "$PID_FILE"
