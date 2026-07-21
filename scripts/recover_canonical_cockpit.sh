#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${MCLEOD_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

if [[ ! -f "$PROJECT_ROOT/cockpit.py" ]]; then
  echo "ERROR: Canonical cockpit.py not found at $PROJECT_ROOT"
  exit 1
fi

cd "$PROJECT_ROOT"
"$PROJECT_ROOT/scripts/maintenance/assert_canonical_repo.sh" "$PROJECT_ROOT"
echo "Using project root: $PROJECT_ROOT"

# Ensure env file exists for live credentials.
if [[ ! -f ".env" ]]; then
  echo "ERROR: Missing .env in $PROJECT_ROOT"
  echo "Copy your live .env into this folder, then re-run."
  exit 1
fi

# Ensure token file exists.
if [[ ! -f "token.json" ]]; then
  echo "ERROR: Missing token.json in $PROJECT_ROOT"
  echo "Run auth_test.py once to generate token.json, then re-run."
  exit 1
fi

# Stop existing local cockpit/bot processes.
pkill -f "cockpit.py" || true
pkill -f "phase3_monitor.py" || true

# Start cockpit in canonical-friendly local mode.
export MCLEOD_CANONICAL_RUNTIME_HOST="${MCLEOD_CANONICAL_RUNTIME_HOST:-$(hostname)}"
export ACCOUNT_MODE=live
export SCHWAB_CALLBACK_URL="https://127.0.0.1"

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/opt/python@3.11/bin/python3.11}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="/usr/bin/python3"
fi

nohup "$PYTHON_BIN" "$PROJECT_ROOT/cockpit.py" > "$PROJECT_ROOT/cockpit_stdout.log" 2>&1 &
CC_PID=$!
echo "Started cockpit PID: $CC_PID"

# Wait briefly for API.
for _ in {1..20}; do
  if curl -sf "http://127.0.0.1:5001/api/status" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Clear parity lock and start bot.
curl -sf -X POST "http://127.0.0.1:5001/api/parity/baseline" >/dev/null
curl -sf -X POST "http://127.0.0.1:5001/api/start" >/dev/null

# Print concise health snapshot.
"$PYTHON_BIN" - <<'PY'
import json, urllib.request
base='http://127.0.0.1:5001'
with urllib.request.urlopen(base+'/api/status', timeout=10) as r:
    s=json.loads(r.read().decode())
print('bot_running=', s.get('bot_running'))
print('bot_running_effective=', s.get('bot_running_effective'))
print('trade_entry_reason=', s.get('trade_entry_reason'))
PY

echo "Recovery complete. Verify the Cloudflare Tunnel routes the public Cockpit to the private origin."
