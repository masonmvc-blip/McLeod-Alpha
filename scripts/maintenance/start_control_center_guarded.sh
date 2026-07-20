#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
CANONICAL_HOST="${MCLEOD_CANONICAL_RUNTIME_HOST:-$(hostname)}"
PYTHON_BIN="${PYTHON_BIN:-}"
RUN_BACKGROUND="${RUN_BACKGROUND:-0}"
REQUIRED_ACCOUNT_MODE="${MCLEOD_REQUIRED_ACCOUNT_MODE:-live}"
REQUIRED_SCHWAB_CALLBACK_URL="${MCLEOD_REQUIRED_SCHWAB_CALLBACK_URL:-https://127.0.0.1:8182}"
REQUIRED_REDIRECT_FLAG="${MCLEOD_REQUIRED_REDIRECT_NONCANONICAL_CONTROL_CENTER:-0}"
TRADE_DB_PATH="$ROOT/data/mcleod_alpha.db"
CONTROL_CENTER_PID_FILE="$ROOT/.control_center_pid"

db_has_trade_log_table() {
  local db_path="$1"
  "$PYTHON_BIN" - "$db_path" <<'PY' >/dev/null 2>&1
import os
import sqlite3
import sys

path = sys.argv[1]
if not os.path.exists(path) or os.path.getsize(path) <= 0:
    raise SystemExit(1)

try:
    con = sqlite3.connect(path)
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trade_log' LIMIT 1"
    ).fetchone()
    con.close()
except Exception:
    raise SystemExit(1)

raise SystemExit(0 if row else 1)
PY
}

bootstrap_trade_log_schema() {
  "$PYTHON_BIN" - <<'PY' >/dev/null
from execution.trade_logger import init_trade_log
init_trade_log()
PY
}

restore_trade_db_if_needed() {
  mkdir -p "$ROOT/data"

  if db_has_trade_log_table "$TRADE_DB_PATH"; then
    echo "trade_db_check=OK path=$TRADE_DB_PATH"
    return 0
  fi

  echo "trade_db_check=INVALID path=$TRADE_DB_PATH"

  local restore_candidates=()
  if [[ -n "${MCLEOD_DB_RESTORE_SOURCE:-}" ]]; then
    restore_candidates+=("${MCLEOD_DB_RESTORE_SOURCE}")
  fi
  restore_candidates+=(
    "$HOME/Library/CloudStorage/Dropbox/McLeod Capital/McLeod Alpha - Dropbox Backup/data/mcleod_alpha.db"
    "$HOME/Library/CloudStorage/Dropbox/McLeod Capital/McLeod Alpha/data/mcleod_alpha.db"
    "$ROOT/data/mcleod_alpha.db.backup"
  )

  local src
  for src in "${restore_candidates[@]}"; do
    if [[ "$src" == "$TRADE_DB_PATH" ]]; then
      continue
    fi
    if db_has_trade_log_table "$src"; then
      cp "$src" "$TRADE_DB_PATH"
      echo "trade_db_restored_from=$src"
      break
    fi
  done

  if ! db_has_trade_log_table "$TRADE_DB_PATH"; then
    echo "trade_db_restore_fallback=bootstrap_schema"
    bootstrap_trade_log_schema
  fi

  if db_has_trade_log_table "$TRADE_DB_PATH"; then
    echo "trade_db_check=HEALED path=$TRADE_DB_PATH"
    "$PYTHON_BIN" - "$TRADE_DB_PATH" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
con = sqlite3.connect(path)
count = con.execute("SELECT COUNT(*) FROM trade_log").fetchone()[0]
con.close()
print(f"trade_db_trade_log_rows={count}")
PY
    return 0
  fi

  echo "ERROR: trade_db remains invalid after restore/bootstrap attempts"
  exit 1
}

python_has_required_modules() {
  local py="$1"
  "$py" - <<'PY' >/dev/null 2>&1
import flask
import dotenv
import schwab
PY
}

resolve_python_bin() {
  if [[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]]; then
    if python_has_required_modules "$PYTHON_BIN"; then
      echo "$PYTHON_BIN"
      return 0
    fi
    echo "ERROR: provided PYTHON_BIN missing required modules (flask, dotenv, schwab): $PYTHON_BIN" >&2
    return 1
  fi

  local candidates=(
    "/opt/homebrew/opt/python@3.11/bin/python3.11"
    "$ROOT/.venv/bin/python"
    "$ROOT/.venv/bin/python3"
  )

  local py
  for py in "${candidates[@]}"; do
    if [[ -x "$py" ]] && python_has_required_modules "$py"; then
      echo "$py"
      return 0
    fi
  done

  if command -v python3 >/dev/null 2>&1; then
    py="$(command -v python3)"
    if python_has_required_modules "$py"; then
      echo "$py"
      return 0
    fi
  fi

  echo "ERROR: no Python with required modules found (flask, dotenv, schwab)" >&2
  return 1
}

PYTHON_BIN="$(resolve_python_bin)"

cd "$ROOT"
"$ROOT/scripts/maintenance/assert_canonical_repo.sh" "$ROOT"

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

if [[ "${ACCOUNT_MODE:-$REQUIRED_ACCOUNT_MODE}" != "$REQUIRED_ACCOUNT_MODE" ]]; then
  echo "ERROR: ACCOUNT_MODE mismatch (current=${ACCOUNT_MODE:-unset}, required=$REQUIRED_ACCOUNT_MODE)"
  exit 1
fi

if [[ "${SCHWAB_CALLBACK_URL:-$REQUIRED_SCHWAB_CALLBACK_URL}" != "$REQUIRED_SCHWAB_CALLBACK_URL" ]]; then
  echo "ERROR: SCHWAB_CALLBACK_URL mismatch (current=${SCHWAB_CALLBACK_URL:-unset}, required=$REQUIRED_SCHWAB_CALLBACK_URL)"
  exit 1
fi

if [[ "${MCLEOD_REDIRECT_NONCANONICAL_CONTROL_CENTER:-$REQUIRED_REDIRECT_FLAG}" != "$REQUIRED_REDIRECT_FLAG" ]]; then
  echo "ERROR: MCLEOD_REDIRECT_NONCANONICAL_CONTROL_CENTER mismatch (current=${MCLEOD_REDIRECT_NONCANONICAL_CONTROL_CENTER:-unset}, required=$REQUIRED_REDIRECT_FLAG)"
  exit 1
fi

restore_trade_db_if_needed

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
  MCLEOD_REDIRECT_NONCANONICAL_CONTROL_CENTER="$REQUIRED_REDIRECT_FLAG" \
  ENFORCE_RUNTIME_CONFIG_ON_START=1 \
  ENFORCE_CLEAN_GIT_ON_START="${ENFORCE_CLEAN_GIT_ON_START:-1}" \
  ACCOUNT_MODE="$REQUIRED_ACCOUNT_MODE" \
  SCHWAB_CALLBACK_URL="$REQUIRED_SCHWAB_CALLBACK_URL" \
  nohup "$PYTHON_BIN" "$ROOT/control_center.py" > "$ROOT/control_center_stdout.log" 2>&1 &
  control_center_pid=$!
  echo "$control_center_pid" > "$CONTROL_CENTER_PID_FILE"
  echo "control_center started in background pid=$control_center_pid"
else
  AUTO_REEXEC_ON_CONTROL_CENTER_CHANGE=0 \
  MCLEOD_CANONICAL_RUNTIME_HOST="$CANONICAL_HOST" \
  MCLEOD_REDIRECT_NONCANONICAL_CONTROL_CENTER="$REQUIRED_REDIRECT_FLAG" \
  ENFORCE_RUNTIME_CONFIG_ON_START=1 \
  ENFORCE_CLEAN_GIT_ON_START="${ENFORCE_CLEAN_GIT_ON_START:-1}" \
  ACCOUNT_MODE="$REQUIRED_ACCOUNT_MODE" \
  SCHWAB_CALLBACK_URL="$REQUIRED_SCHWAB_CALLBACK_URL" \
  "$PYTHON_BIN" "$ROOT/control_center.py"
fi
