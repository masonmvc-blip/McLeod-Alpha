#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WATCHDOG_PID_FILE="$PROJECT_DIR/.runtime_watchdog.pid"
CC_PID_FILE="$PROJECT_DIR/.control_center_pid"
MANUAL_STOP_MARKER="$PROJECT_DIR/data/bot_manual_stop_marker.json"
RUNTIME_EVENTS_FILE="$PROJECT_DIR/data/reports/runtime_events.jsonl"
RUNTIME_ALERT_FLAG_FILE="$PROJECT_DIR/data/runtime_alert_flag.json"
CANONICAL_RUNTIME_HOST="${MCLEOD_CANONICAL_RUNTIME_HOST:-Masons-iMac.local}"

if [[ -x "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14" ]]; then
  PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14"
elif [[ -x "$PROJECT_DIR/.venv/bin/python3" ]]; then
  PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
elif [[ -x "$PROJECT_DIR/venv/bin/python3" ]]; then
  PYTHON_BIN="$PROJECT_DIR/venv/bin/python3"
else
  PYTHON_BIN="python3"
fi

WATCHDOG_INTERVAL_SEC="${WATCHDOG_INTERVAL_SEC:-15}"
MIN_RESTART_GAP_SEC="${MIN_RESTART_GAP_SEC:-45}"
RESTART_WINDOW_SEC="${RESTART_WINDOW_SEC:-900}"
MAX_CC_RESTARTS_PER_WINDOW="${MAX_CC_RESTARTS_PER_WINDOW:-5}"
MAX_BOT_RESTARTS_PER_WINDOW="${MAX_BOT_RESTARTS_PER_WINDOW:-5}"
OPS_SUMMARY_EVERY_LOOPS="${OPS_SUMMARY_EVERY_LOOPS:-40}"

cd "$PROJECT_DIR"
echo "$$" > "$WATCHDOG_PID_FILE"

last_cc_restart=0
last_bot_restart=0
loop_count=0
cc_window_start=0
cc_window_count=0
bot_window_start=0
bot_window_count=0

emit_event() {
  local event_type="$1"
  local severity="$2"
  local message="$3"
  shift 3
  local details="$*"

  mkdir -p "$(dirname "$RUNTIME_EVENTS_FILE")"
  "$PYTHON_BIN" - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

path = Path(r"$RUNTIME_EVENTS_FILE")
payload = {
    "ts": datetime.now(timezone.utc).isoformat(),
    "event_type": "$event_type",
    "severity": "$severity",
    "message": "$message",
    "details": "$details",
}
with path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(payload) + "\n")
PY
}

emit_alert_flag() {
  local severity="$1"
  local message="$2"
  local event_type="$3"

  mkdir -p "$(dirname "$RUNTIME_ALERT_FLAG_FILE")"
  "$PYTHON_BIN" - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

path = Path(r"$RUNTIME_ALERT_FLAG_FILE")
payload = {
    "active": True,
    "severity": "$severity",
    "event_type": "$event_type",
    "message": "$message",
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
PY
}

runtime_host_allows_bot_start() {
  local current_host
  current_host="$(hostname)"
  [[ -z "$CANONICAL_RUNTIME_HOST" || "${current_host:l}" == "${CANONICAL_RUNTIME_HOST:l}" ]]
}

restart_control_center_process() {
  nohup "$SCRIPT_DIR/run_control_center_waitress.sh" >> "$PROJECT_DIR/logs/control_center.log" 2>&1 < /dev/null &
  cc_pid=$!
  echo "$cc_pid" > "$CC_PID_FILE"
}

restart_budget_ok() {
  local kind="$1"
  local now_ts
  now_ts=$(date +%s)

  if [[ "$kind" == "cc" ]]; then
    if (( cc_window_start == 0 || (now_ts - cc_window_start) > RESTART_WINDOW_SEC )); then
      cc_window_start=$now_ts
      cc_window_count=0
    fi
    if (( cc_window_count >= MAX_CC_RESTARTS_PER_WINDOW )); then
      emit_event "watchdog_restart_limited" "warn" "Control Center restart budget exhausted" "count=$cc_window_count window_sec=$RESTART_WINDOW_SEC"
      emit_alert_flag "warn" "Control Center restart budget exhausted" "watchdog_restart_limited"
      return 1
    fi
    cc_window_count=$((cc_window_count + 1))
    return 0
  fi

  if (( bot_window_start == 0 || (now_ts - bot_window_start) > RESTART_WINDOW_SEC )); then
    bot_window_start=$now_ts
    bot_window_count=0
  fi
  if (( bot_window_count >= MAX_BOT_RESTARTS_PER_WINDOW )); then
    emit_event "watchdog_restart_limited" "warn" "Bot restart budget exhausted" "count=$bot_window_count window_sec=$RESTART_WINDOW_SEC"
    emit_alert_flag "warn" "Bot restart budget exhausted" "watchdog_restart_limited"
    return 1
  fi
  bot_window_count=$((bot_window_count + 1))
  return 0
}

is_port_open() {
  lsof -nP -iTCP:5001 -sTCP:LISTEN >/dev/null 2>&1
}

restart_control_center() {
  now_ts=$(date +%s)
  if (( now_ts - last_cc_restart < MIN_RESTART_GAP_SEC )); then
    emit_event "watchdog_restart_skipped" "info" "Control Center restart skipped due cooldown" "cooldown_sec=$MIN_RESTART_GAP_SEC"
    return 0
  fi

  if ! restart_budget_ok "cc"; then
    return 0
  fi

  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Control Center not listening, restarting..."
  restart_control_center_process
  last_cc_restart=$now_ts
  emit_event "watchdog_restart" "warn" "Control Center restarted" "pid=$cc_pid"
}

maybe_restart_bot() {
  if ! runtime_host_allows_bot_start; then
    emit_event "watchdog_bot_start_blocked_host" "info" "Bot restart skipped on non-canonical host" "current_host=$(hostname) allowed_host=$CANONICAL_RUNTIME_HOST"
    return 0
  fi

  if [[ -f "$MANUAL_STOP_MARKER" ]]; then
    return 0
  fi

  now_ts=$(date +%s)
  if (( now_ts - last_bot_restart < MIN_RESTART_GAP_SEC )); then
    return 0
  fi

  # Query status; when bot_running is false we issue a start command.
  bot_running=$(
    "$PYTHON_BIN" - <<'PY'
import json
import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:5001/api/status", timeout=6) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    print("1" if payload.get("bot_running") else "0")
except Exception:
    print("1")
PY
  )

  if [[ "$bot_running" == "1" ]]; then
    return 0
  fi

  if ! restart_budget_ok "bot"; then
    return 0
  fi

  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bot not running, requesting start..."
  if "$PYTHON_BIN" - <<'PY'
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
raise SystemExit(0 if payload.get("status") in {"success", "ok"} else 1)
PY
  then
    last_bot_restart=$now_ts
    emit_event "watchdog_restart" "warn" "Bot restart requested via API" "mode=api_start"
  else
    emit_event "watchdog_restart_failed" "error" "Bot restart API request failed" "endpoint=/api/start"
    emit_alert_flag "error" "Bot restart API request failed" "watchdog_restart_failed"
  fi
}

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Runtime watchdog online (interval ${WATCHDOG_INTERVAL_SEC}s)"
emit_event "watchdog_start" "info" "Runtime watchdog online" "interval_sec=$WATCHDOG_INTERVAL_SEC"

while true; do
  if ! is_port_open; then
    emit_event "watchdog_health" "warn" "Control Center port not listening" "port=5001"
    restart_control_center
  fi

  if is_port_open; then
    maybe_restart_bot
  fi

  loop_count=$((loop_count + 1))
  if (( loop_count % 20 == 0 )); then
    "$SCRIPT_DIR/rotate_runtime_logs.sh" || true
  fi

  if (( OPS_SUMMARY_EVERY_LOOPS > 0 )) && (( loop_count % OPS_SUMMARY_EVERY_LOOPS == 0 )); then
    if "$PYTHON_BIN" "$SCRIPT_DIR/generate_ops_summary.py" >/dev/null 2>&1; then
      emit_event "ops_summary_generated" "info" "Ops summary generated" "every_loops=$OPS_SUMMARY_EVERY_LOOPS"
    else
      emit_event "ops_summary_failed" "warn" "Ops summary generation failed" "every_loops=$OPS_SUMMARY_EVERY_LOOPS"
      emit_alert_flag "warn" "Ops summary generation failed" "ops_summary_failed"
    fi
  fi

  sleep "$WATCHDOG_INTERVAL_SEC"
done
