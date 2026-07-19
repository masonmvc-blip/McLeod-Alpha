#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
CONFIG_FILE="$ROOT_DIR/data/ibd_auto_export.env"

URL="${1:-${IBD_EXPORT_URL:-}}"
SELECTORS="${2:-${IBD_EXPORT_SELECTORS:-button:has-text('Export')||button:has-text('CSV')||a:has-text('Export')||a:has-text('Download')}}"
HEADED="${IBD_EXPORT_HEADED:-}"

if [[ -z "${URL:-}" ]]; then
  echo "Usage: scripts/desktop/configure_ibd_auto_export.sh <ibd_export_url> [selectors]"
  exit 2
fi

mkdir -p "$ROOT_DIR/data"
cat > "$CONFIG_FILE" <<EOF
IBD_EXPORT_URL="$URL"
IBD_EXPORT_SELECTORS="$SELECTORS"
IBD_EXPORT_HEADED="$HEADED"
IBD_IMPORT_SOURCE_DIR="${IBD_IMPORT_SOURCE_DIR:-$HOME/Downloads/IBD}"
IBD_IMPORT_GLOB="${IBD_IMPORT_GLOB:-ibd*.csv}"
EOF

echo "Saved IBD auto-export config: $CONFIG_FILE"
echo "URL: $URL"
