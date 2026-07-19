#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
PY="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="/usr/bin/python3"
fi

CONFIG_FILE="$ROOT_DIR/data/ibd_auto_export.env"
if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

EXPORT_URL="${IBD_EXPORT_URL:-}"
SOURCE_DIR="${IBD_IMPORT_SOURCE_DIR:-$HOME/Downloads/IBD}"
GLOB_PATTERN="${IBD_IMPORT_GLOB:-ibd*.csv}"

mkdir -p "$SOURCE_DIR"

export_rc=0
if [[ -n "$EXPORT_URL" ]]; then
  "$PY" "$ROOT_DIR/scripts/desktop/export_ibd_via_browser.py" \
    --export-url "$EXPORT_URL" \
    --download-dir "$SOURCE_DIR" \
    --selectors "${IBD_EXPORT_SELECTORS:-button:has-text('Export')||button:has-text('CSV')||a:has-text('Export')||a:has-text('Download')}" \
    ${IBD_EXPORT_HEADED:+--headed} || export_rc=$?
else
  echo "IBD_EXPORT_URL not set; skipping browser export step"
fi

"$PY" "$ROOT_DIR/scripts/desktop/auto_import_ibd_csv.py" \
  --source-dir "$SOURCE_DIR" \
  --glob "$GLOB_PATTERN" || import_rc=$?

import_rc=${import_rc:-0}
if [[ "$import_rc" -ne 0 ]]; then
  exit "$import_rc"
fi

# Import success is sufficient for pipeline freshness, even if export step skipped.
exit 0
