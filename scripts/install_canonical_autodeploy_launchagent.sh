#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
AGENT_ID="com.mcleod.alpha.canonical-autodeploy-hot"
PLIST_PATH="$HOME/Library/LaunchAgents/$AGENT_ID.plist"
LOG_PATH="$ROOT_DIR/logs/canonical_autodeploy_launchd.log"
WATCH_SCRIPT="$ROOT_DIR/scripts/maintenance/canonical_autodeploy_watch.sh"
LOCAL_RUNNER_DIR="$HOME/Library/Application Support/McLeod Alpha"
RUNNER_PATH="$LOCAL_RUNNER_DIR/canonical_autodeploy_watch.sh"

MODE="${1:-normal}"
case "$MODE" in
  normal)
    MODE_POLL_SECONDS="15"
    ;;
  market-hot)
    MODE_POLL_SECONDS="5"
    ;;
  custom)
    MODE_POLL_SECONDS="${MCLEOD_AUTODEPLOY_POLL_SECONDS:-15}"
    ;;
  *)
    echo "Usage: $0 [normal|market-hot|custom]"
    echo "  normal     -> 15s poll (default)"
    echo "  market-hot -> 5s poll"
    echo "  custom     -> uses MCLEOD_AUTODEPLOY_POLL_SECONDS env"
    exit 1
    ;;
esac

POLL_SECONDS="${MCLEOD_AUTODEPLOY_POLL_SECONDS:-$MODE_POLL_SECONDS}"

if [[ ! -x "$WATCH_SCRIPT" ]]; then
  echo "ERROR: autodeploy watcher is not executable: $WATCH_SCRIPT"
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOCAL_RUNNER_DIR"
mkdir -p "$ROOT_DIR/logs"
cp "$WATCH_SCRIPT" "$RUNNER_PATH"
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

    <key>WorkingDirectory</key>
    <string>$ROOT_DIR</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>EnvironmentVariables</key>
    <dict>
      <key>MCLEOD_CANONICAL_RUNTIME_HOST</key>
      <string>${MCLEOD_CANONICAL_RUNTIME_HOST:-Desktop}</string>
      <key>MCLEOD_AUTODEPLOY_POLL_SECONDS</key>
      <string>$POLL_SECONDS</string>
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
launchctl kickstart -k "gui/$(id -u)/$AGENT_ID"

echo "Installed LaunchAgent: $AGENT_ID"
echo "Plist: $PLIST_PATH"
echo "Log: $LOG_PATH"
echo "Mode: $MODE"
echo "Poll seconds: $POLL_SECONDS"
