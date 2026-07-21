#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
source "$ROOT/config/cockpit.env"
CANONICAL_HOST="${MCLEOD_CANONICAL_RUNTIME_HOST:-Desktop}"
BASE_URL="${MCLEOD_BASE_URL:-http://127.0.0.1:5001}"
CANONICAL_URL="$COCKPIT_PUBLIC_URL"
REQUIRE_CLEAN_REPO_FOR_LOCK="${MCLEOD_GOLIVE_REQUIRE_CLEAN_REPO_FOR_LOCK:-1}"
SESSION_GUARD="$ROOT/scripts/maintenance/market_session_guard.sh"

cd "$ROOT"
. "$SESSION_GUARD"
"$ROOT/scripts/maintenance/assert_canonical_repo.sh" "$ROOT"

if ! mcleod_market_change_allowed; then
  mcleod_market_change_block_message
  exit 1
fi

if [[ "$(hostname | tr '[:upper:]' '[:lower:]')" != "$(echo "$CANONICAL_HOST" | tr '[:upper:]' '[:lower:]')" ]]; then
  echo "ERROR: go-live is Desktop-only"
  echo "current_host=$(hostname) expected_host=$CANONICAL_HOST"
  exit 1
fi

echo "go_live=starting"
echo "root=$ROOT"
echo "host=$(hostname) canonical_host=$CANONICAL_HOST"

dirty=0
if [[ -n "$(git status --porcelain)" ]]; then
  dirty=1
fi

if [[ "$dirty" == "0" ]]; then
  echo "go_live_sync_mode=lock_canonical_runtime"
  "$ROOT/scripts/maintenance/lock_canonical_runtime.sh"
else
  echo "go_live_sync_mode=current_worktree"
  echo "go_live_repo_dirty=1"
  if [[ "$REQUIRE_CLEAN_REPO_FOR_LOCK" == "1" ]]; then
    echo "go_live_lock_skipped_due_dirty_repo=1"
  fi
  ENFORCE_CLEAN_GIT_ON_START=0 RUN_BACKGROUND=1 MCLEOD_CANONICAL_RUNTIME_HOST="$CANONICAL_HOST" \
    "$ROOT/scripts/maintenance/start_cockpit_guarded.sh"

  for _ in {1..40}; do
    if curl -sf "$BASE_URL/api/status" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  curl -sS -X POST "$BASE_URL/api/parity/baseline" >/dev/null
fi

curl -sS -X POST "$BASE_URL/api/start-direct" >/dev/null

python3 - <<'PY' "$CANONICAL_URL"
import json
import ssl
import sys
import urllib.request

url = sys.argv[1].rstrip('/') + '/api/status'
ctx = ssl._create_unverified_context() if url.startswith('https://') else None
req = urllib.request.Request(url, headers={'Cache-Control': 'no-cache'})
with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
    s = json.loads(resp.read().decode('utf-8'))

fp = s.get('runtime_fingerprint') or {}
checks = {
    'parity_state': str(s.get('parity_state') or ''),
    'parity_block_start': bool(s.get('parity_block_start')),
    'bot_running_effective': bool(s.get('bot_running_effective')),
    'runtime_host_is_canonical': bool(s.get('runtime_host_is_canonical')),
}

print('parity_state=' + checks['parity_state'])
print('parity_block_start=' + str(checks['parity_block_start']))
print('bot_running_effective=' + str(checks['bot_running_effective']))
print('runtime_host=' + str(fp.get('hostname')))
print('runtime_host_is_canonical=' + str(checks['runtime_host_is_canonical']))

if checks['parity_state'].upper() != 'MATCH':
    raise SystemExit('FAIL: parity_state is not MATCH')
if checks['parity_block_start']:
    raise SystemExit('FAIL: parity_block_start is true')
if not checks['bot_running_effective']:
    raise SystemExit('FAIL: bot_running_effective is false')
if not checks['runtime_host_is_canonical']:
    raise SystemExit('FAIL: runtime_host_is_canonical is false')

print('go_live_status=PASS')
PY

echo "go_live=complete"
