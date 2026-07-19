#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
AGENT_ID="com.mcleod.decision.audit.watchdog"
PLIST_PATH="$HOME/Library/LaunchAgents/$AGENT_ID.plist"
LOG_PATH="$HOME/Library/Logs/mcleod_decision_audit_watchdog.log"
RUNNER_PATH="$ROOT_DIR/scripts/run_decision_audit_watchdog.sh"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$HOME/Library/Logs"

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

    <key>StartInterval</key>
    <integer>300</integer>

    <key>WorkingDirectory</key>
    <string>$ROOT_DIR</string>

    <key>EnvironmentVariables</key>
    <dict>
      <key>TZ</key>
      <string>America/New_York</string>
      <key>PYTHONUNBUFFERED</key>
      <string>1</string>
      <key>DECISION_AUDIT_MAX_AGE_MINUTES</key>
      <string>7</string>
      <key>DECISION_AUDIT_ALERT_COOLDOWN_MINUTES</key>
      <string>20</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

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
  launchctl kickstart -k "gui/$(id -u)/$AGENT_ID"
fi

echo "Installed LaunchAgent: $AGENT_ID"
echo "Plist: $PLIST_PATH"
echo "Log: $LOG_PATH"
echo "Schedule: every 5 minutes during market hours via script gating"
