#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
AGENT_ID="com.mcleod.alpha.cio-report"
LEGACY_AGENT_ID="com.mcleod.morning.cio.email"
PLIST_PATH="$HOME/Library/LaunchAgents/$AGENT_ID.plist"
LEGACY_PLIST_PATH="$HOME/Library/LaunchAgents/$LEGACY_AGENT_ID.plist"
LOG_PATH="$ROOT_DIR/logs/morning_cio_email_launchd.log"
LOCAL_RUNNER_DIR="$HOME/Library/Application Support/McLeod Alpha"
LOCAL_RUNNER_PATH="$LOCAL_RUNNER_DIR/run_morning_cio_email.sh"

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
mkdir -p "$LOCAL_RUNNER_DIR"

cat > "$LOCAL_RUNNER_PATH" <<WRAPPER
#!/usr/bin/env zsh
set -euo pipefail
cd '$ROOT_DIR'
export PYTHONPATH='$ROOT_DIR'
if '$PYTHON_PATH' '$ROOT_DIR/tools/send_cio_report.py' --send; then
  rc=0
else
  rc=\$?
fi
'$PYTHON_PATH' '$ROOT_DIR/scripts/verify_morning_cio_contract.py' || true
'$PYTHON_PATH' '$ROOT_DIR/ops/check_morning_cio_health.py' --require-smtp --max-age-hours 26 || true
exit \$rc
WRAPPER

chmod 755 "$LOCAL_RUNNER_PATH"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$ROOT_DIR/logs"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>$AGENT_ID</string>

    <key>ProgramArguments</key>
    <array>
      <string>/bin/zsh</string>
      <string>$LOCAL_RUNNER_PATH</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key>
      <integer>7</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>

    <key>WorkingDirectory</key>
    <string>$ROOT_DIR</string>

    <key>EnvironmentVariables</key>
    <dict>
      <key>TZ</key>
      <string>America/Chicago</string>
      <key>PYTHONUNBUFFERED</key>
      <string>1</string>
    </dict>

    <key>StandardOutPath</key>
    <string>$LOG_PATH</string>

    <key>StandardErrorPath</key>
    <string>$LOG_PATH</string>
  </dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LEGACY_AGENT_ID" >/dev/null 2>&1 || true
launchctl disable "gui/$(id -u)/$LEGACY_AGENT_ID" >/dev/null 2>&1 || true
if [[ -f "$LEGACY_PLIST_PATH" ]]; then
  mv "$LEGACY_PLIST_PATH" "$LEGACY_PLIST_PATH.disabled"
fi

launchctl bootout "gui/$(id -u)/$AGENT_ID" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$AGENT_ID"

if [[ "${1:-}" == "--run-now" ]]; then
  /bin/zsh "$LOCAL_RUNNER_PATH"
fi

echo "Installed LaunchAgent: $AGENT_ID"
echo "Plist: $PLIST_PATH"
echo "Log: $LOG_PATH"
echo "Schedule: 7:00 AM America/Chicago via XNYS session gating in cio_email.morning_report"
