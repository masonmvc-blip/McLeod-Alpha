#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
AGENT_ID="com.mcleod.alpha.spcx-daily-accumulator"
PLIST_PATH="$HOME/Library/LaunchAgents/$AGENT_ID.plist"
RUNTIME_ROOT="$HOME/Library/Application Support/McLeod Alpha/runtime"
LOG_PATH="$RUNTIME_ROOT/logs/spcx_daily_accumulator_launchd.log"
RUNNER_PATH="$HOME/Library/Application Support/McLeod Alpha/run_spcx_daily_accumulator.sh"

if [[ "$ROOT_DIR" != "$HOME/GitHub/McLeod-Alpha-New" ]]; then
  echo "Refusing install: run this from the canonical GitHub checkout at $HOME/GitHub/McLeod-Alpha-New" >&2
  exit 2
fi

mkdir -p "$HOME/Library/LaunchAgents" "$RUNTIME_ROOT/logs"

cat > "$RUNNER_PATH" <<WRAPPER
#!/usr/bin/env zsh
set -euo pipefail
cd '$ROOT_DIR'
exec '$ROOT_DIR/.venv/bin/python' '$ROOT_DIR/scripts/spcx_daily_accumulator.py' --execute
WRAPPER
chmod 755 "$RUNNER_PATH"

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
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
  </array>
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

echo "Installed GitHub-only LaunchAgent at $PLIST_PATH"
echo "Schedule: Monday-Friday at 08:30 Central on this Mac."
echo "Live execution still requires SPCX_AUTOMATION_LIVE_ACK=SPCX_ONE_SHARE_DAILY_LIVE."
