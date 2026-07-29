#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="${RUNTIME_LOG_PROJECT_DIR:-$DEFAULT_PROJECT_DIR}"
MAX_SIZE_BYTES="${RUNTIME_LOG_MAX_SIZE_BYTES:-$((10 * 1024 * 1024))}"
TELEMETRY_MAX_SIZE_BYTES="${RUNTIME_TELEMETRY_MAX_SIZE_BYTES:-$((25 * 1024 * 1024))}"
KEEP_FILES="${RUNTIME_LOG_KEEP_FILES:-14}"

cd "$PROJECT_DIR"
mkdir -p logs

rotate_if_needed() {
  local file="$1"
  local max_size="${2:-$MAX_SIZE_BYTES}"
  local recreate="${3:-true}"
  if [[ ! -f "$file" ]]; then
    return
  fi

  local size
  size=$(stat -f%z "$file" 2>/dev/null || echo 0)
  if (( size < max_size )); then
    return
  fi

  local ts
  ts="${RUNTIME_LOG_ROTATION_TIMESTAMP:-$(date +"%Y%m%d-%H%M%S")}"
  local rotated="${file}.${ts}"
  local collision=1
  while [[ -e "$rotated" ]]; do
    rotated="${file}.${ts}.${collision}"
    collision=$((collision + 1))
  done

  mv "$file" "$rotated"
  if [[ "$recreate" == "true" ]]; then
    : > "$file"
  fi

  local old_files
  old_files=$(ls -1t "${file}."* 2>/dev/null | tail -n +$((KEEP_FILES + 1)) || true)
  if [[ -n "$old_files" ]]; then
    echo "$old_files" | xargs rm -f
  fi
}

rotate_if_needed "bot_output.log"
rotate_if_needed "logs/cockpit.log"
rotate_if_needed "logs/spcx_open_assist.log"
rotate_if_needed "logs/preopen_health_bundle.log"
rotate_if_needed "data/reports/latency_cycle_history.jsonl" "$TELEMETRY_MAX_SIZE_BYTES" false
rotate_if_needed "data/reports/decision_audit_history.jsonl" "$TELEMETRY_MAX_SIZE_BYTES" false
rotate_if_needed "data/reports/internet_quality_history.jsonl" "$TELEMETRY_MAX_SIZE_BYTES" false
rotate_if_needed "data/reports/runtime_events.jsonl" "$TELEMETRY_MAX_SIZE_BYTES" false
