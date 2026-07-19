#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
LOCAL_RUNTIME_ROOT="$HOME/Library/Application Support/McLeod Alpha/runtime"
LOCAL_LOGS="$LOCAL_RUNTIME_ROOT/logs"
LOCAL_REPORTS="$LOCAL_RUNTIME_ROOT/reports"

mkdir -p "$LOCAL_LOGS" "$LOCAL_REPORTS"

link_dir() {
  local src="$1"
  local dst="$2"

  if [[ -L "$src" ]]; then
    echo "Already symlinked: $src"
    return
  fi

  if [[ -d "$src" ]]; then
    rsync -a "$src/" "$dst/"
    mv "$src" "${src}.dropbox_backup_$(date +%Y%m%d_%H%M%S)"
  fi

  ln -s "$dst" "$src"
  echo "Linked $src -> $dst"
}

# Move high-churn runtime outputs off Dropbox sync hot path.
link_dir "$ROOT_DIR/logs" "$LOCAL_LOGS"
link_dir "$ROOT_DIR/data/reports/spcx_open_assist" "$LOCAL_REPORTS/spcx_open_assist"

echo "Runtime artifacts relocated to local runtime root: $LOCAL_RUNTIME_ROOT"
