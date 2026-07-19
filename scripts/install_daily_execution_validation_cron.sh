#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
LOG_PATH="$HOME/Library/Logs/mcleod_daily_execution_validation.log"
CRON_SCHEDULE="20 16 * * 1-5"
JOB_CMD="cd \"$ROOT_DIR\" && /bin/zsh \"$ROOT_DIR/scripts/run_daily_execution_validation.sh\" >> \"$LOG_PATH\" 2>&1"
JOB_LINE="$CRON_SCHEDULE $JOB_CMD"

mkdir -p "$HOME/Library/Logs"

EXISTING_CRON="$(crontab -l 2>/dev/null || true)"

# Remove old entries for this job path to avoid duplicates.
FILTERED="$(printf "%s\n" "$EXISTING_CRON" | grep -v "run_daily_execution_validation.sh" || true)"

if [[ -n "$FILTERED" ]]; then
  printf "%s\n%s\n" "$FILTERED" "$JOB_LINE" | crontab -
else
  printf "%s\n" "$JOB_LINE" | crontab -
fi

echo "Installed cron schedule: $CRON_SCHEDULE (Mon-Fri)"
echo "Command: $JOB_CMD"
