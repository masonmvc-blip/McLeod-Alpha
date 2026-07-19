#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
AGENT_ID="com.mcleod.alpha.auto-publish"
PLIST_PATH="$HOME/Library/LaunchAgents/$AGENT_ID.plist"
LOG_PATH="$ROOT_DIR/logs/auto_publish_launchd.log"
WATCH_SCRIPT="$ROOT_DIR/scripts/maintenance/auto_publish_watch.sh"
RUNNER_PATH="$HOME/.local/bin/mcleod_auto_publish_watch.sh"

[[ -x "$WATCH_SCRIPT" ]] || { echo "ERROR: watcher is not executable: $WATCH_SCRIPT"; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.local/bin" "$ROOT_DIR/logs"

cat > "$RUNNER_PATH" <<RUNNER
#!/usr/bin/env zsh
set -euo pipefail
export MCLEOD_ROOT='$ROOT_DIR'
exec /bin/bash '$WATCH_SCRIPT'
RUNNER
chmod 755 "$RUNNER_PATH"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$AGENT_ID</string>
  <key>Program</key><string>$RUNNER_PATH</string>
  <key>WorkingDirectory</key><string>$ROOT_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG_PATH</string>
  <key>StandardErrorPath</key><string>$LOG_PATH</string>
</dict></plist>
PLIST

launchctl bootout "gui/$(id -u)/$AGENT_ID" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$AGENT_ID"
launchctl kickstart -k "gui/$(id -u)/$AGENT_ID"
echo "Installed auto-publish LaunchAgent: $AGENT_ID"