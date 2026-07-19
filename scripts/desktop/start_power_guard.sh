#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
PID_FILE="$ROOT_DIR/.power_guard.pid"
LOG_FILE="$ROOT_DIR/logs/power_guard.log"

mkdir -p "$ROOT_DIR/logs"

if [[ -f "$PID_FILE" ]]; then
  existing_pid=$(cat "$PID_FILE" 2>/dev/null || true)
  if [[ -n "${existing_pid:-}" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "Power guard already running (PID: $existing_pid)"
    exit 0
  fi
fi

# Prevent idle sleep/display sleep while bot infrastructure is active.
nohup caffeinate -dimsu > "$LOG_FILE" 2>&1 &
pid=$!
echo "$pid" > "$PID_FILE"

echo "Power guard started (PID: $pid)"
echo "Log: $LOG_FILE"
