#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
AGENT_ID="com.mcleod.alpha.daily-trade-learning"
PLIST_PATH="$HOME/Library/LaunchAgents/$AGENT_ID.plist"
LOG_PATH="$ROOT_DIR/logs/daily_trade_learning_launchd.log"
RUNNER_PATH="$ROOT_DIR/scripts/run_daily_trade_learning.sh"

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
      <string>$RUNNER_PATH</string>
    </array>

    <key>StartCalendarInterval</key>
    <array>
      <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>35</integer></dict>
      <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>35</integer></dict>
      <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>35</integer></dict>
      <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>35</integer></dict>
      <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>35</integer></dict>
    </array>

    <key>WorkingDirectory</key>
    <string>$ROOT_DIR</string>

    <key>EnvironmentVariables</key>
    <dict>
      <key>TZ</key>
      <string>America/New_York</string>
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

chmod 755 "$RUNNER_PATH"

launchctl bootout "gui/$(id -u)/$AGENT_ID" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$AGENT_ID"

if [[ "${1:-}" == "--run-now" ]]; then
  launchctl kickstart -k "gui/$(id -u)/$AGENT_ID"
fi

echo "Installed LaunchAgent: $AGENT_ID"
echo "Plist: $PLIST_PATH"
echo "Log: $LOG_PATH"
echo "Schedule: Mon-Fri 16:35 America/New_York"
