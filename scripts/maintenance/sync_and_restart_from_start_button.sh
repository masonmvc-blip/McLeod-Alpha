#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
REMOTE="${MCLEOD_GIT_REMOTE:-origin}"
BRANCH="${MCLEOD_GIT_BRANCH:-main}"
BASE_URL="${MCLEOD_BASE_URL:-http://127.0.0.1:5001}"
CANONICAL_HOST="${MCLEOD_CANONICAL_RUNTIME_HOST:-$(hostname)}"

cd "$ROOT"
"$ROOT/scripts/maintenance/assert_canonical_repo.sh" "$ROOT"

if [[ "$(hostname | tr '[:upper:]' '[:lower:]')" != "$(echo "$CANONICAL_HOST" | tr '[:upper:]' '[:lower:]')" ]]; then
  echo "ERROR: sync and restart must run on $CANONICAL_HOST; current host is $(hostname)"
  exit 1
fi

echo "start_button_sync=starting at $(date '+%Y-%m-%d %H:%M:%S %Z')"
git fetch "$REMOTE" "$BRANCH"
git merge --ff-only "$REMOTE/$BRANCH"

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

curl -sf -X POST "$BASE_URL/api/parity/baseline" >/dev/null
bot_start_payload="$(curl -sS -X POST "$BASE_URL/api/start-direct" -H 'Content-Type: application/json')"
echo "bot_start=$bot_start_payload"
printf '%s' "$bot_start_payload" | python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("status") == "success" else 1)'

echo "start_button_sync=complete"