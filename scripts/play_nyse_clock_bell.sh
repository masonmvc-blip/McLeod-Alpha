#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
AUDIO_PATH="$ROOT_DIR/static/audio/nyse_bell.mp3"
LOG_PATH="$ROOT_DIR/logs/nyse_clock_bell.log"
EVENT="${1:-market_bell}"
MAX_PLAY_SECONDS=5

mkdir -p "$ROOT_DIR/logs"

if [[ ! -x /usr/bin/afplay || ! -f "$AUDIO_PATH" ]]; then
  print -r -- "$(date '+%Y-%m-%d %H:%M:%S %Z') | $EVENT | unavailable" >> "$LOG_PATH"
  exit 1
fi

print -r -- "$(date '+%Y-%m-%d %H:%M:%S %Z') | $EVENT | playing for ${MAX_PLAY_SECONDS}s" >> "$LOG_PATH"

if [[ "${MCLEOD_BELL_DRY_RUN:-0}" == "1" ]]; then
  exit 0
fi

exec /usr/bin/afplay -t "$MAX_PLAY_SECONDS" "$AUDIO_PATH"