#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOCAL_RUNNER_DIR="$HOME/Library/Application Support/McLeod Alpha"

mkdir -p "$LAUNCH_DIR" "$LOCAL_RUNNER_DIR" "$ROOT_DIR/logs"

write_runner() {
  local path="$1"
  local body="$2"
  /bin/cat > "$path" <<EOF
#!/usr/bin/env zsh
set -euo pipefail
cd '$ROOT_DIR'
$body
EOF
  /bin/chmod 755 "$path"
}

install_agent() {
  local label="$1"
  local runner_path="$2"
  local plist_path="$LAUNCH_DIR/$label.plist"
  local schedule_block="$3"
  local log_path="$4"

  /bin/cat > "$plist_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>$label</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/zsh</string>
      <string>$runner_path</string>
    </array>
    $schedule_block
    <key>WorkingDirectory</key><string>$ROOT_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>TZ</key><string>America/New_York</string>
      <key>PYTHONUNBUFFERED</key><string>1</string>
    </dict>
    <key>StandardOutPath</key><string>$log_path</string>
    <key>StandardErrorPath</key><string>$log_path</string>
  </dict>
</plist>
PLIST

  /bin/launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
  /bin/launchctl bootstrap "gui/$(id -u)" "$plist_path"
  /bin/launchctl enable "gui/$(id -u)/$label"
}

# Power guard start/stop for market window.
POWER_START_RUNNER="$LOCAL_RUNNER_DIR/power_guard_start.sh"
POWER_STOP_RUNNER="$LOCAL_RUNNER_DIR/power_guard_stop.sh"
write_runner "$POWER_START_RUNNER" "'$ROOT_DIR/scripts/desktop/start_power_guard.sh'"
write_runner "$POWER_STOP_RUNNER" "'$ROOT_DIR/scripts/desktop/stop_power_guard.sh'"

install_agent \
  "com.mcleod.alpha.power-guard-start" \
  "$POWER_START_RUNNER" \
  "<key>StartCalendarInterval</key><array><dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>20</integer></dict><dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>20</integer></dict><dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>20</integer></dict><dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>20</integer></dict><dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>20</integer></dict></array>" \
  "$ROOT_DIR/logs/power_guard_start_launchd.log"

install_agent \
  "com.mcleod.alpha.power-guard-stop" \
  "$POWER_STOP_RUNNER" \
  "<key>StartCalendarInterval</key><array><dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>10</integer></dict><dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>10</integer></dict><dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>10</integer></dict><dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>10</integer></dict><dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>10</integer></dict></array>" \
  "$ROOT_DIR/logs/power_guard_stop_launchd.log"

# Pre-open health bundle weekdays.
PREOPEN_RUNNER="$LOCAL_RUNNER_DIR/preopen_health_bundle.sh"
write_runner "$PREOPEN_RUNNER" "'$ROOT_DIR/scripts/desktop/run_preopen_health_bundle.sh'"

install_agent \
  "com.mcleod.alpha.preopen-health-bundle" \
  "$PREOPEN_RUNNER" \
  "<key>StartCalendarInterval</key><array><dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>15</integer></dict><dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>15</integer></dict><dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>15</integer></dict><dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>15</integer></dict><dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>15</integer></dict></array>" \
  "$ROOT_DIR/logs/preopen_health_bundle_launchd.log"

# Daily runtime log rotation.
ROTATE_RUNNER="$LOCAL_RUNNER_DIR/runtime_log_rotation.sh"
write_runner "$ROTATE_RUNNER" "'$ROOT_DIR/ops/rotate_runtime_logs.sh'"

install_agent \
  "com.mcleod.alpha.runtime-log-rotation" \
  "$ROTATE_RUNNER" \
  "<key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>5</integer></dict>" \
  "$ROOT_DIR/logs/runtime_log_rotation_launchd.log"

echo "Installed launch agents:"
echo "- com.mcleod.alpha.power-guard-start"
echo "- com.mcleod.alpha.power-guard-stop"
echo "- com.mcleod.alpha.preopen-health-bundle"
echo "- com.mcleod.alpha.runtime-log-rotation"
