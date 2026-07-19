#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
PY="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="/usr/bin/python3"
fi

LOG="$ROOT_DIR/logs/preopen_health_bundle.log"
mkdir -p "$ROOT_DIR/logs"

run_step() {
  local name="$1"
  shift
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] STEP: $name" | tee -a "$LOG"
  if "$@" >> "$LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] PASS: $name" | tee -a "$LOG"
    return 0
  else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] FAIL: $name" | tee -a "$LOG"
    return 1
  fi
}

overall=0
run_step "desktop_preflight" "$ROOT_DIR/scripts/desktop/desktop_performance_preflight.sh" || overall=1
run_step "repo_hygiene" "$ROOT_DIR/scripts/maintenance/check_repo_hygiene.sh" || overall=1
run_step "morning_cio_health" "$PY" "$ROOT_DIR/ops/check_morning_cio_health.py" --require-smtp --max-age-hours 26 || overall=1
run_step "ibd_auto_import_health" "$PY" "$ROOT_DIR/ops/check_ibd_auto_import_health.py" --max-age-hours 30 || overall=1
run_step "log_rotation" "$ROOT_DIR/ops/rotate_runtime_logs.sh" || overall=1

if [[ "$overall" == "0" ]]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] PREOPEN_BUNDLE: PASS" | tee -a "$LOG"
  exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] PREOPEN_BUNDLE: FAIL" | tee -a "$LOG"
exit 2
