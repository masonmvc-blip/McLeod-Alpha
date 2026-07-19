#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
REMOTE="${MCLEOD_GIT_REMOTE:-origin}"
BRANCH="${MCLEOD_GIT_BRANCH:-main}"
BASE_URL="${MCLEOD_BASE_URL:-http://127.0.0.1:5001}"
CANONICAL_URL="${MCLEOD_CANONICAL_CONTROL_CENTER_URL:-https://masons-imac.tailb88bd7.ts.net}"

cd "$ROOT"
"$ROOT/scripts/maintenance/assert_canonical_repo.sh" "$ROOT"

echo "Lock canonical runtime"
echo "root=$ROOT"
echo "remote=$REMOTE branch=$BRANCH"

if [[ -n "$(git status --porcelain)" ]]; then
  STASH_NAME="auto-lock-$(date +%Y%m%d-%H%M%S)"
  git stash push -u -m "$STASH_NAME" || true
  echo "stashed_local_changes=$STASH_NAME"
fi

git fetch "$REMOTE"
git checkout "$BRANCH"
git reset --hard "$REMOTE/$BRANCH"

ENFORCE_CLEAN_GIT_ON_START=0 RUN_BACKGROUND=1 "$ROOT/scripts/maintenance/start_control_center_guarded.sh"

for _ in {1..30}; do
  if curl -sf "$BASE_URL/api/status" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

LOCAL_SCHEMA="$(curl -sS "$BASE_URL/api/status" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status_schema_version") or "unknown")')"
echo "local_schema=$LOCAL_SCHEMA"

if ps axww -o command= | grep -F "$ROOT/control_center.py" | grep -Fv grep >/dev/null 2>&1; then
  echo "process_path_check=OK ($ROOT/control_center.py)"
else
  echo "process_path_check=FAILED"
  exit 1
fi

echo "canonical_checks"
curl -sS "$CANONICAL_URL/api/status" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("canonical_schema=" + str(d.get("status_schema_version") or "unknown")); print("canonical_host=" + str((d.get("runtime_fingerprint") or {}).get("hostname") or "unknown"))'
curl -sS "$CANONICAL_URL" | grep -nE "Parity|Today's Trades" | sed -n '1,40p'

echo "lock_complete=1"
