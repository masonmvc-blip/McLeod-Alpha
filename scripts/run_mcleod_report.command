#!/bin/bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${WORKSPACE_DIR}" || exit 1

if [[ -f "venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
elif [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

PYTHON_BIN="$(command -v python || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

"${PYTHON_BIN}" "scripts/run_mcleod_report.py"
status=$?

if [[ ${status} -ne 0 ]]; then
  echo
  echo "McLeod report workflow failed (exit ${status})."
  echo "See logs/mcleod_report_latest.log for details."
  read -r -n 1 -s -p "Press any key to close this window..."
  echo
  exit ${status}
fi

if command -v code >/dev/null 2>&1; then
  code --reuse-window "reports/mcleod_core_rankings_latest.md" >/dev/null 2>&1 || true
else
  open -a "Visual Studio Code" "reports/mcleod_core_rankings_latest.md" >/dev/null 2>&1 || true
fi

exit 0
