#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
LABEL="com.mcleod.alpha.ibd-auto-import"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
RUNNER_DIR="$HOME/Library/Application Support/McLeod Alpha"
RUNNER_PATH="$RUNNER_DIR/run_ibd_auto_import.sh"
LOG_PATH="$ROOT_DIR/logs/ibd_auto_import_launchd.log"
WATCH_PATH="${IBD_IMPORT_SOURCE_DIR:-$HOME/Downloads/IBD}"

mkdir -p "$HOME/Library/LaunchAgents" "$RUNNER_DIR" "$ROOT_DIR/logs"

mkdir -p "$WATCH_PATH"

cat > "$RUNNER_PATH" <<WRAPPER
#!/usr/bin/env zsh
set -euo pipefail
cd '$ROOT_DIR'

PY='$ROOT_DIR/.venv/bin/python'
if [[ ! -x "\$PY" ]]; then
  PY='/usr/bin/python3'
fi

CONFIG_FILE='$ROOT_DIR/data/ibd_auto_export.env'
if [[ -f "\$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "\$CONFIG_FILE"
fi

EXPORT_URL="\${IBD_EXPORT_URL:-}"
SOURCE_DIR="\${IBD_IMPORT_SOURCE_DIR:-$HOME/Downloads/IBD}"
GLOB_PATTERN="\${IBD_IMPORT_GLOB:-ibd*.csv}"

mkdir -p "\$SOURCE_DIR"

if [[ -n "\$EXPORT_URL" ]]; then
  "\$PY" '$ROOT_DIR/scripts/desktop/export_ibd_via_browser.py' \
    --export-url "\$EXPORT_URL" \
    --download-dir "\$SOURCE_DIR" \
    --selectors "\${IBD_EXPORT_SELECTORS:-button:has-text('Export')||button:has-text('CSV')||a:has-text('Export')||a:has-text('Download')}" \
    \${IBD_EXPORT_HEADED:+--headed} || true
fi

"\$PY" '$ROOT_DIR/scripts/desktop/auto_import_ibd_csv.py' --source-dir "\$SOURCE_DIR" --glob "\$GLOB_PATTERN"
WRAPPER
chmod 755 "$RUNNER_PATH"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
      <string>/bin/zsh</string>
      <string>$RUNNER_PATH</string>
    </array>

    <key>WatchPaths</key>
    <array>
      <string>$WATCH_PATH</string>
    </array>

    <key>StartCalendarInterval</key>
    <array>
      <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>40</integer></dict>
      <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>40</integer></dict>
      <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>40</integer></dict>
      <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>40</integer></dict>
      <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>40</integer></dict>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
      <key>TZ</key>
      <string>America/Chicago</string>
      <key>PYTHONUNBUFFERED</key>
      <string>1</string>
      <key>IBD_IMPORT_SOURCE_DIR</key>
      <string>$WATCH_PATH</string>
      <key>IBD_IMPORT_GLOB</key>
      <string>ibd*.csv</string>
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

launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$LABEL"

echo "Installed LaunchAgent: $LABEL"
echo "Plist: $PLIST_PATH"
echo "Watch path: $WATCH_PATH"
echo "Log: $LOG_PATH"

if [[ "${1:-}" == "--run-now" ]]; then
  /bin/zsh "$RUNNER_PATH"
fi
