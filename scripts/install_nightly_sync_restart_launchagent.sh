#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$ROOT_DIR/config/cockpit.env"
AGENT_ID="com.mcleod.alpha.nightly-sync-restart"
PLIST_PATH="$HOME/Library/LaunchAgents/$AGENT_ID.plist"
LOG_PATH="$ROOT_DIR/logs/nightly_sync_restart_launchd.log"
RUNNER_PATH="$ROOT_DIR/scripts/maintenance/nightly_sync_and_restart.sh"

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT_DIR/logs"

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
      <string>$RUNNER_PATH</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key>
      <integer>2</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>

    <key>WorkingDirectory</key>
    <string>$ROOT_DIR</string>

    <key>EnvironmentVariables</key>
    <dict>
      <key>MCLEOD_CANONICAL_RUNTIME_HOST</key>
      <string>${MCLEOD_CANONICAL_RUNTIME_HOST:-Desktop}</string>
      <key>COCKPIT_PUBLIC_URL</key>
      <string>$COCKPIT_PUBLIC_URL</string>
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

launchctl bootout "gui/$(id -u)/$AGENT_ID" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$AGENT_ID"

echo "Installed LaunchAgent: $AGENT_ID"
echo "Schedule: daily at 2:00 AM (system local time)"
echo "Log: $LOG_PATH"

if [[ "${1:-}" == "--run-now" ]]; then
  /bin/zsh "$RUNNER_PATH"
fi