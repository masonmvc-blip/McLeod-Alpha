#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
REMOTE="${MCLEOD_GIT_REMOTE:-origin}"
BRANCH="${MCLEOD_GIT_BRANCH:-main}"
INTERVAL_SECONDS="${MCLEOD_AUTODEPLOY_POLL_SECONDS:-15}"
STATE_FILE="${MCLEOD_AUTODEPLOY_STATE_FILE:-$ROOT/data/autodeploy_last_sha.txt}"
LOCK_SCRIPT="$ROOT/scripts/maintenance/lock_canonical_runtime.sh"
CANONICAL_HOST="${MCLEOD_CANONICAL_RUNTIME_HOST:-$(hostname)}"
LOCK_RETRY_ATTEMPTS="${MCLEOD_AUTODEPLOY_LOCK_RETRY_ATTEMPTS:-3}"
LOCK_RETRY_SLEEP_SECONDS="${MCLEOD_AUTODEPLOY_LOCK_RETRY_SLEEP_SECONDS:-8}"
SESSION_GUARD="$ROOT/scripts/maintenance/market_session_guard.sh"

cd "$ROOT"
. "$SESSION_GUARD"
"$ROOT/scripts/maintenance/assert_canonical_repo.sh" "$ROOT"

if [[ ! -x "$LOCK_SCRIPT" ]]; then
  echo "ERROR: lock script not executable: $LOCK_SCRIPT"
  exit 1
fi

if [[ "$(hostname | tr '[:upper:]' '[:lower:]')" != "$(echo "$CANONICAL_HOST" | tr '[:upper:]' '[:lower:]')" ]]; then
  echo "ERROR: this watcher must run on canonical host"
  echo "current_host=$(hostname) expected_host=$CANONICAL_HOST"
  exit 1
fi

mkdir -p "$(dirname "$STATE_FILE")"
touch "$STATE_FILE"

echo "canonical_autodeploy_watch=starting"
echo "root=$ROOT"
echo "remote=$REMOTE branch=$BRANCH poll_seconds=$INTERVAL_SECONDS"
echo "lock_retry_attempts=$LOCK_RETRY_ATTEMPTS lock_retry_sleep_seconds=$LOCK_RETRY_SLEEP_SECONDS"

last_seen_sha="$(cat "$STATE_FILE" 2>/dev/null || true)"

while true; do
  git fetch "$REMOTE" "$BRANCH" >/dev/null 2>&1 || {
    echo "autodeploy_fetch_failed at $(date '+%Y-%m-%d %H:%M:%S')"
    sleep "$INTERVAL_SECONDS"
    continue
  }

  remote_sha="$(git rev-parse "$REMOTE/$BRANCH")"
  local_sha="$(git rev-parse HEAD)"

  if [[ "$remote_sha" != "$last_seen_sha" || "$remote_sha" != "$local_sha" ]]; then
    if ! mcleod_market_change_allowed; then
      mcleod_market_change_block_message
      sleep "$INTERVAL_SECONDS"
      continue
    fi
    echo "autodeploy_detected_change local=$local_sha remote=$remote_sha at $(date '+%Y-%m-%d %H:%M:%S')"
    applied=0
    for ((attempt=1; attempt<=LOCK_RETRY_ATTEMPTS; attempt++)); do
      if "$LOCK_SCRIPT"; then
        applied=1
        break
      fi
      echo "autodeploy_apply_retry attempt=$attempt remote=$remote_sha"
      sleep "$LOCK_RETRY_SLEEP_SECONDS"
    done

    if [[ "$applied" == "1" ]]; then
      last_seen_sha="$remote_sha"
      printf '%s\n' "$last_seen_sha" > "$STATE_FILE"
      echo "autodeploy_applied sha=$last_seen_sha"
    else
      echo "autodeploy_apply_failed remote=$remote_sha"
    fi
  fi

  sleep "$INTERVAL_SECONDS"
done
