#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

run_health_check() {
  local pybin="$1"
  "$pybin" "$ROOT_DIR/scripts/verify_morning_cio_contract.py" || true
  "$pybin" "$ROOT_DIR/ops/check_morning_cio_health.py" --require-approved-transport --max-age-hours 26 || true
}

pick_python() {
  local candidate
  for candidate in \
    "$ROOT_DIR/.venv-1/bin/python" \
    "$ROOT_DIR/.venv/bin/python" \
    "$ROOT_DIR/venv/bin/python" \
    "$HOME/Library/Application Support/McLeod Alpha/venv/bin/python" \
    /opt/homebrew/bin/python3.11 \
    /usr/bin/python3; do
    if [[ -x "$candidate" ]] && "$candidate" -c 'import dotenv, exchange_calendars, pandas' >/dev/null 2>&1; then
      print -r -- "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_PATH="$(pick_python)" || {
  echo "ERROR: no Python interpreter has the Morning CIO dependencies"
  exit 70
}

if "$PYTHON_PATH" "$ROOT_DIR/tools/send_cio_report.py" --send; then
  rc=0
else
  rc=$?
fi
run_health_check "$PYTHON_PATH"
exit $rc
