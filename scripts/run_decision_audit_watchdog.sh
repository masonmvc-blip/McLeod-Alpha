#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PY="$ROOT_DIR/.venv/bin/python"
elif [[ -x "$ROOT_DIR/venv/bin/python" ]]; then
  PY="$ROOT_DIR/venv/bin/python"
else
  PY="/usr/bin/python3"
fi

cd "$ROOT_DIR"
"$PY" "$ROOT_DIR/scripts/check_decision_audit_watchdog.py"
