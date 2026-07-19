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

PREFERRED_PY311="/opt/homebrew/bin/python3.11"
if [[ -x "${PREFERRED_PY311}" ]]; then
  if ! "${PYTHON_BIN}" -c "import schwab" >/dev/null 2>&1; then
    PYTHON_BIN="${PREFERRED_PY311}"
  fi
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "ERROR: No python interpreter found" >&2
  exit 1
fi

exec "${PYTHON_BIN}" "scripts/run_mcleod_report.py"
