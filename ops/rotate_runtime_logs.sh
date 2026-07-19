#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MAX_SIZE_BYTES=$((10 * 1024 * 1024))
KEEP_FILES=14

cd "$PROJECT_DIR"
mkdir -p logs

rotate_if_needed() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    return
  fi

  local size
  size=$(stat -f%z "$file" 2>/dev/null || echo 0)
  if (( size < MAX_SIZE_BYTES )); then
    return
  fi

  local ts
  ts=$(date +"%Y%m%d-%H%M%S")
  local rotated="${file}.${ts}"

  mv "$file" "$rotated"
  : > "$file"

  local old_files
  old_files=$(ls -1t "${file}."* 2>/dev/null | tail -n +$((KEEP_FILES + 1)) || true)
  if [[ -n "$old_files" ]]; then
    echo "$old_files" | xargs rm -f
  fi
}

rotate_if_needed "bot_output.log"
rotate_if_needed "logs/control_center.log"
rotate_if_needed "logs/spcx_open_assist.log"
rotate_if_needed "logs/preopen_health_bundle.log"
