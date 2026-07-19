#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
CANONICAL_HOST="${MCLEOD_CANONICAL_RUNTIME_HOST:-Desktop}"
LOCK_SCRIPT="$ROOT/scripts/maintenance/lock_canonical_runtime.sh"

cd "$ROOT"
"$ROOT/scripts/maintenance/assert_canonical_repo.sh" "$ROOT"

if [[ "$(hostname | tr '[:upper:]' '[:lower:]')" != "$(echo "$CANONICAL_HOST" | tr '[:upper:]' '[:lower:]')" ]]; then
  echo "ERROR: nightly sync must run on $CANONICAL_HOST; current host is $(hostname)"
  exit 1
fi

if [[ ! -x "$LOCK_SCRIPT" ]]; then
  echo "ERROR: canonical runtime lock script is not executable: $LOCK_SCRIPT"
  exit 1
fi

echo "nightly_sync_and_restart=starting at $(date '+%Y-%m-%d %H:%M:%S %Z')"
exec "$LOCK_SCRIPT"