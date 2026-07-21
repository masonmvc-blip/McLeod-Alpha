#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
LOCK_SCRIPT="$ROOT/scripts/maintenance/lock_canonical_runtime.sh"

cd "$ROOT"
"$ROOT/scripts/maintenance/assert_canonical_repo.sh" "$ROOT"

if [[ ! -x "$LOCK_SCRIPT" ]]; then
  echo "ERROR: canonical runtime lock script is not executable: $LOCK_SCRIPT"
  exit 1
fi

echo "nightly_sync_and_restart=starting at $(date '+%Y-%m-%d %H:%M:%S %Z')"
exec "$LOCK_SCRIPT"