#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
DAYS="${LATENCY_INSIGHTS_DAYS:-7}"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [[ -x "$ROOT_DIR/venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/venv/bin/python"
else
  PYTHON_BIN="/usr/bin/python3"
fi

cd "$ROOT_DIR"
"$PYTHON_BIN" "$ROOT_DIR/scripts/send_daily_latency_email.py" --send --days "$DAYS"
