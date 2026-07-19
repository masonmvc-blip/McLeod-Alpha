#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
REMOTE="${MCLEOD_GIT_REMOTE:-origin}"
BRANCH="${MCLEOD_GIT_BRANCH:-main}"
BASE_URL="${MCLEOD_BASE_URL:-http://127.0.0.1:5001}"
CANONICAL_URL="${MCLEOD_CANONICAL_CONTROL_CENTER_URL:-https://masons-imac.tailb88bd7.ts.net}"
PARITY_VERIFY_ATTEMPTS="${MCLEOD_PARITY_VERIFY_ATTEMPTS:-12}"
PARITY_VERIFY_SLEEP_SECONDS="${MCLEOD_PARITY_VERIFY_SLEEP_SECONDS:-2}"

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

MCLEOD_REQUIRED_ACCOUNT_MODE="${MCLEOD_REQUIRED_ACCOUNT_MODE:-live}" \
MCLEOD_REQUIRED_SCHWAB_CALLBACK_URL="${MCLEOD_REQUIRED_SCHWAB_CALLBACK_URL:-https://127.0.0.1}" \
MCLEOD_REQUIRED_REDIRECT_NONCANONICAL_CONTROL_CENTER="${MCLEOD_REQUIRED_REDIRECT_NONCANONICAL_CONTROL_CENTER:-0}" \
ENFORCE_CLEAN_GIT_ON_START=0 RUN_BACKGROUND=1 "$ROOT/scripts/maintenance/start_control_center_guarded.sh"

for _ in {1..30}; do
  if curl -sf "$BASE_URL/api/status" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Refresh parity baseline after each lock cycle, then require MATCH before success.
curl -sS -X POST "$BASE_URL/api/parity/baseline" >/dev/null || true

parity_ok=0
for ((i=1; i<=PARITY_VERIFY_ATTEMPTS; i++)); do
  parity_state="$(curl -sS "$BASE_URL/api/status" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(str(d.get("parity_state") or "UNKNOWN"))' 2>/dev/null || echo UNKNOWN)"
  parity_block_start="$(curl -sS "$BASE_URL/api/status" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("1" if d.get("parity_block_start") else "0")' 2>/dev/null || echo 1)"
  if [[ "$parity_state" == "MATCH" && "$parity_block_start" == "0" ]]; then
    parity_ok=1
    echo "parity_check=OK attempt=$i state=$parity_state block_start=$parity_block_start"
    break
  fi
  echo "parity_check=retry attempt=$i state=$parity_state block_start=$parity_block_start"
  sleep "$PARITY_VERIFY_SLEEP_SECONDS"
done

if [[ "$parity_ok" != "1" ]]; then
  echo "ERROR: parity did not converge to MATCH after lock cycle"
  curl -sS "$BASE_URL/api/status" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("parity_state=" + str(d.get("parity_state"))); print("parity_block_start=" + str(d.get("parity_block_start"))); print("parity_issues=" + str(d.get("parity_issues")));'
  exit 1
fi

bot_start_payload="$(curl -sS -X POST "$BASE_URL/api/start-direct" -H 'Content-Type: application/json')"
echo "bot_start=$bot_start_payload"
if ! printf '%s' "$bot_start_payload" | python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("status") == "success" else 1)'; then
  echo "ERROR: bot did not start after canonical runtime lock"
  exit 1
fi

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

if [[ -x "$ROOT/scripts/maintenance/post_deploy_smoke_check.sh" ]]; then
  "$ROOT/scripts/maintenance/post_deploy_smoke_check.sh" "$BASE_URL" "$CANONICAL_URL"
else
  echo "WARN: smoke check script missing or not executable"
fi

echo "lock_complete=1"
