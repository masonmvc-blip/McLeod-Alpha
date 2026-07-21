#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CC_LOG="$PROJECT_DIR/logs/cockpit.log"
WATCHDOG_LOG="$PROJECT_DIR/logs/runtime_watchdog.log"
CC_PID_FILE="$PROJECT_DIR/.cockpit_pid"
WATCHDOG_PID_FILE="$PROJECT_DIR/.runtime_watchdog.pid"

if [[ -x "/opt/homebrew/opt/python@3.11/bin/python3.11" ]]; then
  PYTHON_BIN="/opt/homebrew/opt/python@3.11/bin/python3.11"
elif [[ -x "$PROJECT_DIR/.venv/bin/python3" ]]; then
  PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
elif [[ -x "$PROJECT_DIR/venv/bin/python3" ]]; then
  PYTHON_BIN="$PROJECT_DIR/venv/bin/python3"
else
  PYTHON_BIN="python3"
fi

cd "$PROJECT_DIR"
mkdir -p logs

is_port_open() {
  lsof -nP -iTCP:5001 -sTCP:LISTEN >/dev/null 2>&1
}

start_cockpit_waitress() {
  nohup "$SCRIPT_DIR/run_cockpit_waitress.sh" >> "$CC_LOG" 2>&1 < /dev/null &
  cc_pid=$!
  echo "$cc_pid" > "$CC_PID_FILE"
}

start_cockpit() {
  if is_port_open; then
    echo "Cockpit already listening on 127.0.0.1:5001"
    return 0
  fi

  echo "Starting Cockpit (Waitress)..."
  start_cockpit_waitress

  for _ in {1..30}; do
    if is_port_open; then
      echo "Cockpit started (PID $cc_pid)"
      return 0
    fi
    sleep 0.5
  done

  echo "Cockpit failed to bind port 5001; check logs/cockpit.log"
  return 1
}

start_bot_via_api() {
  bot_pid=""
  if [[ -f .bot_pid ]]; then
    bot_pid="$(cat .bot_pid 2>/dev/null || true)"
  fi

  if [[ -n "$bot_pid" ]] && kill -0 "$bot_pid" 2>/dev/null; then
    echo "Bot already running (PID $bot_pid)"
    return 0
  fi

  echo "Starting bot through Cockpit API..."
  "$PYTHON_BIN" - <<'PY'
import json
import urllib.request

req = urllib.request.Request(
    "http://127.0.0.1:5001/api/start",
    data=b"{}",
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(req, timeout=10) as resp:
    payload = json.loads(resp.read().decode("utf-8"))

print(payload.get("message", payload))
if payload.get("status") not in {"success", "ok"}:
    raise SystemExit(1)
PY
}

start_watchdog() {
  if [[ -f "$WATCHDOG_PID_FILE" ]]; then
    old_pid="$(cat "$WATCHDOG_PID_FILE" 2>/dev/null || true)"
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
      echo "Runtime watchdog already running (PID $old_pid)"
      return 0
    fi
  fi

  echo "Starting runtime watchdog..."
  nohup "$SCRIPT_DIR/runtime_watchdog.sh" >> "$WATCHDOG_LOG" 2>&1 < /dev/null &
  wd_pid=$!
  echo "$wd_pid" > "$WATCHDOG_PID_FILE"
  echo "Runtime watchdog started (PID $wd_pid)"
}

"$SCRIPT_DIR/rotate_runtime_logs.sh" || true
start_cockpit
start_bot_via_api
start_watchdog

echo ""
echo "Stack status:"
"$SCRIPT_DIR/stack_status.sh"
