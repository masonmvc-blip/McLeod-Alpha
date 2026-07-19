#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
PY="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="/usr/bin/python3"
fi

SOURCE_DIR="${IBD_IMPORT_SOURCE_DIR:-$HOME/Downloads/IBD}"
GLOB_PATTERN="${IBD_IMPORT_GLOB:-ibd*.csv}"

cd "$ROOT_DIR"
"$PY" "$ROOT_DIR/scripts/desktop/auto_import_ibd_csv.py" --source-dir "$SOURCE_DIR" --glob "$GLOB_PATTERN" "$@"
