#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${WORKSPACE_DIR}"

if [[ -f "venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
elif [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

PYTHON_BIN="$(command -v python || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "ERROR: No python interpreter found" >&2
  exit 1
fi

export PYTHONPATH="${WORKSPACE_DIR}:${PYTHONPATH:-}"
"${PYTHON_BIN}" "run_daily_trade_learning.py" "$@"

TRADING_DATE="$("${PYTHON_BIN}" - <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
print(datetime.now(ZoneInfo("America/New_York")).date().isoformat())
PY
)"
REVIEW_ARTIFACT="${WORKSPACE_DIR}/data/learning/mcleod-alpha-trade-review-${TRADING_DATE}.md"
if [[ -f "${REVIEW_ARTIFACT}" ]]; then
  "${PYTHON_BIN}" "scripts/send_daily_bot_trade_review.py" --date "${TRADING_DATE}"
else
  echo "Daily bot review email deferred; artifact not yet available: ${REVIEW_ARTIFACT}"
fi
