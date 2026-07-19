#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
AGENT_ID="com.mcleod.alpha.spcx-open-assist"
PLIST_PATH="$HOME/Library/LaunchAgents/$AGENT_ID.plist"
LOG_PATH="$ROOT_DIR/logs/spcx_open_assist_launchd.log"
LOCAL_RUNNER_DIR="$HOME/Library/Application Support/McLeod Alpha"
LOCAL_RUNNER_PATH="$LOCAL_RUNNER_DIR/run_spcx_open_assist.sh"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$ROOT_DIR/logs"
mkdir -p "$LOCAL_RUNNER_DIR"

cat > "$LOCAL_RUNNER_PATH" <<WRAPPER
#!/usr/bin/env zsh
set -euo pipefail
cd '$ROOT_DIR'
'$ROOT_DIR/scripts/run_spcx_open_assist.sh'
WRAPPER

chmod 755 "$LOCAL_RUNNER_PATH"

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
      <key>Weekday</key>
      <integer>1</integer>
      <key>Hour</key>
      <integer>9</integer>
      <key>Minute</key>
      <integer>29</integer>
    </dict>

    <key>EnvironmentVariables</key>
    <dict>
      <key>TZ</key>
      <string>America/New_York</string>
      <key>PYTHONUNBUFFERED</key>
      <string>1</string>
    </dict>

    <key>WorkingDirectory</key>
    <string>$ROOT_DIR</string>

    <key>StandardOutPath</key>
    <string>$LOG_PATH</string>

    <key>StandardErrorPath</key>
    <string>$LOG_PATH</string>
  </dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$AGENT_ID" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$AGENT_ID"

if [[ "${1:-}" == "--run-now" ]]; then
  /bin/zsh "$LOCAL_RUNNER_PATH"
fi

echo "Installed LaunchAgent: $AGENT_ID"
echo "Plist: $PLIST_PATH"
echo "Log: $LOG_PATH"
echo "Schedule: Monday 09:29 ET (manual alert only, no order placement)"
