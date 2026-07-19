#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
CANONICAL_HOST="${MCLEOD_CANONICAL_RUNTIME_HOST:-$(hostname)}"
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/opt/python@3.11/bin/python3.11}"
RUN_BACKGROUND="${RUN_BACKGROUND:-0}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

cd "$ROOT"

echo "root=$ROOT"
echo "hostname=$(hostname)"
echo "canonical_host=$CANONICAL_HOST"
echo "python=$PYTHON_BIN"

if [[ ! -f "$ROOT/control_center.py" ]]; then
  echo "ERROR: control_center.py not found in $ROOT"
  exit 1
fi

if [[ ! -f "$ROOT/.env" ]]; then
  echo "ERROR: .env missing in $ROOT"
  exit 1
fi

if [[ ! -f "$ROOT/token.json" ]]; then
  echo "ERROR: token.json missing in $ROOT"
  exit 1
fi

if [[ "$(hostname)" != "$CANONICAL_HOST" ]]; then
  echo "ERROR: host mismatch (current=$(hostname), expected=$CANONICAL_HOST)"
  exit 1
fi

# Optional strict cleanliness gate (recommended for canonical runtime).
if [[ "${ENFORCE_CLEAN_GIT_ON_START:-1}" == "1" ]]; then
  if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
    echo "ERROR: git repo is dirty; commit/stash changes before canonical start"
    git -C "$ROOT" status --short | sed -n '1,20p'
    exit 1
  fi
fi

pkill -f "control_center.py" || true
pkill -f "phase3_monitor.py" || true

if [[ "$RUN_BACKGROUND" == "1" ]]; then
  AUTO_REEXEC_ON_CONTROL_CENTER_CHANGE=0 \
  MCLEOD_CANONICAL_RUNTIME_HOST="$CANONICAL_HOST" \
  MCLEOD_REDIRECT_NONCANONICAL_CONTROL_CENTER=0 \
  ENFORCE_RUNTIME_CONFIG_ON_START=1 \
  ENFORCE_CLEAN_GIT_ON_START="${ENFORCE_CLEAN_GIT_ON_START:-1}" \
  ACCOUNT_MODE=live \
  SCHWAB_CALLBACK_URL="https://127.0.0.1" \
  nohup "$PYTHON_BIN" "$ROOT/control_center.py" > "$ROOT/control_center_stdout.log" 2>&1 &
  echo "control_center started in background"
else
  AUTO_REEXEC_ON_CONTROL_CENTER_CHANGE=0 \
  MCLEOD_CANONICAL_RUNTIME_HOST="$CANONICAL_HOST" \
  MCLEOD_REDIRECT_NONCANONICAL_CONTROL_CENTER=0 \
  ENFORCE_RUNTIME_CONFIG_ON_START=1 \
  ENFORCE_CLEAN_GIT_ON_START="${ENFORCE_CLEAN_GIT_ON_START:-1}" \
  ACCOUNT_MODE=live \
  SCHWAB_CALLBACK_URL="https://127.0.0.1" \
  "$PYTHON_BIN" "$ROOT/control_center.py"
fi
