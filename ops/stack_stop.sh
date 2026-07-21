#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WATCHDOG_PID_FILE="$PROJECT_DIR/.runtime_watchdog.pid"
CC_PID_FILE="$PROJECT_DIR/.cockpit_pid"

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

echo "Stopping runtime watchdog..."
if [[ -f "$WATCHDOG_PID_FILE" ]]; then
  wd_pid="$(cat "$WATCHDOG_PID_FILE" 2>/dev/null || true)"
  if [[ -n "$wd_pid" ]] && kill -0 "$wd_pid" 2>/dev/null; then
    kill "$wd_pid" 2>/dev/null || true
  fi
  rm -f "$WATCHDOG_PID_FILE"
fi

echo "Stopping bot via Cockpit API if available..."
"$PYTHON_BIN" - <<'PY'
import urllib.error
import urllib.request

try:
    req = urllib.request.Request(
        "http://127.0.0.1:5001/api/stop",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        print(resp.read().decode("utf-8"))
except Exception:
    pass
PY

echo "Stopping Cockpit listener on port 5001..."
for cc_pid in $(lsof -nP -iTCP:5001 -sTCP:LISTEN -t 2>/dev/null); do
  kill "$cc_pid" 2>/dev/null || true
done
sleep 1
for cc_pid in $(lsof -nP -iTCP:5001 -sTCP:LISTEN -t 2>/dev/null); do
  kill -9 "$cc_pid" 2>/dev/null || true
done

rm -f "$CC_PID_FILE"

echo "Done."
