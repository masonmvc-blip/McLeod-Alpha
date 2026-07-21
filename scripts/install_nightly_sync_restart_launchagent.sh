#!/usr/bin/env zsh
set -euo pipefail

AGENT_ID="com.mcleod.alpha.nightly-sync-restart"
PLIST_PATH="$HOME/Library/LaunchAgents/$AGENT_ID.plist"

launchctl bootout "gui/$(id -u)/$AGENT_ID" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"

echo "Retired LaunchAgent: $AGENT_ID"
echo "The 3:00 AM automatic sync and restart is disabled."
echo "The runtime watchdog remains responsible for keeping Cockpit and an authorized bot available."