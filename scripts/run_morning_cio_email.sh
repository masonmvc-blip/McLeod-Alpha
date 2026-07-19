#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

run_health_check() {
  local pybin="$1"
  "$pybin" "$ROOT_DIR/scripts/verify_morning_cio_contract.py" || true
  "$pybin" "$ROOT_DIR/ops/check_morning_cio_health.py" --require-smtp --max-age-hours 26 || true
}

if [[ -x "$ROOT_DIR/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.venv/bin/activate"
elif [[ -x "$ROOT_DIR/venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/venv/bin/activate"
fi

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  "$ROOT_DIR/.venv/bin/python" -m cio_email.morning_report --send
  rc=$?
  run_health_check "$ROOT_DIR/.venv/bin/python"
  exit $rc
elif [[ -x "$ROOT_DIR/venv/bin/python" ]]; then
  "$ROOT_DIR/venv/bin/python" -m cio_email.morning_report --send
  rc=$?
  run_health_check "$ROOT_DIR/venv/bin/python"
  exit $rc
fi
/usr/bin/python3 -m cio_email.morning_report --send
rc=$?
run_health_check /usr/bin/python3
exit $rc
