#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

URL_A="${MCLEOD_COCKPIT_URL_A:-}"
URL_B="${MCLEOD_COCKPIT_URL_B:-}"
INSECURE="${MCLEOD_COCKPIT_INSECURE:-0}"
INSECURE_FLAG=()

case "$INSECURE" in
  1|true|TRUE|yes|YES|on|ON)
    INSECURE_FLAG=("--insecure")
    ;;
esac

if [[ -z "$URL_A" || -z "$URL_B" ]]; then
  echo "Usage:" >&2
  echo "  MCLEOD_COCKPIT_URL_A=https://desktop-host ..." >&2
  echo "  MCLEOD_COCKPIT_URL_B=https://laptop-host ..." >&2
  echo "  scripts/maintenance/check_cockpit_parity.sh" >&2
  echo >&2
  echo "Or run directly:" >&2
  echo "  python3 ops/check_cockpit_parity.py --url-a <urlA> --url-b <urlB>" >&2
  exit 2
fi

exec python3 ops/check_cockpit_parity.py \
  --url-a "$URL_A" \
  --url-b "$URL_B" \
  --label-a "desktop" \
  --label-b "laptop" \
  "${INSECURE_FLAG[@]}"
