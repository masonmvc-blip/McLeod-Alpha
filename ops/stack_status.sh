#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -x "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14" ]]; then
  PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14"
elif [[ -x "$PROJECT_DIR/.venv/bin/python3" ]]; then
  PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
elif [[ -x "$PROJECT_DIR/venv/bin/python3" ]]; then
  PYTHON_BIN="$PROJECT_DIR/venv/bin/python3"
else
  PYTHON_BIN="python3"
fi

cd "$PROJECT_DIR"

echo "Control Center listener PIDs:"
lsof -nP -iTCP:5001 -sTCP:LISTEN -t 2>/dev/null || echo "none"

echo ""
echo "PID files:"
for f in .control_center_pid .bot_pid .runtime_watchdog.pid; do
  if [[ -f "$f" ]]; then
    echo "$f=$(cat "$f" 2>/dev/null || true)"
  else
    echo "$f=missing"
  fi
done

echo ""
echo "API status summary:"
"$PYTHON_BIN" - <<'PY'
import json
import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:5001/api/status", timeout=8) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    keys = [
        "bot_running",
        "bot_running_effective",
        "mode",
        "trade_entry_reason",
        "continuation_last_test_at",
        "continuation_call_passed",
        "continuation_put_passed",
    ]
    for key in keys:
        print(f"{key}={payload.get(key)}")
except Exception as e:
    print(f"api_error={e}")
PY
