#!/usr/bin/env zsh
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
REMOTE="${MCLEOD_GIT_REMOTE:-origin}"
BRANCH="${MCLEOD_GIT_BRANCH:-main}"
MAX_RESTART_ATTEMPTS="${MCLEOD_NIGHTLY_RESTART_ATTEMPTS:-2}"
HEALTH_CHECK_ATTEMPTS="${MCLEOD_NIGHTLY_HEALTH_CHECK_ATTEMPTS:-30}"
HEALTH_CHECK_SLEEP_SECONDS="${MCLEOD_NIGHTLY_HEALTH_CHECK_SLEEP_SECONDS:-2}"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$ROOT"
"$ROOT/scripts/maintenance/assert_canonical_repo.sh" "$ROOT"

pick_python() {
  local candidate
  for candidate in "$ROOT/.venv-1/bin/python3" "$ROOT/.venv/bin/python3" "$ROOT/venv/bin/python3" /usr/bin/python3; do
    if [[ -x "$candidate" ]]; then
      print -r -- "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(pick_python)" || {
  echo "ERROR: no Python interpreter is available for nightly health checks"
  exit 1
}

is_stack_healthy() {
  "$PYTHON_BIN" - <<'PY'
import json
import sys
import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:5001/api/status", timeout=8) as response:
        status = json.loads(response.read().decode("utf-8"))
except Exception as exc:
    print(f"health_check=unavailable error={exc}")
    raise SystemExit(1)

healthy = bool(status.get("bot_running_effective"))
print(
    "health_check=" + ("healthy" if healthy else "unhealthy")
    + f" bot_running={status.get('bot_running')}"
    + f" bot_running_effective={status.get('bot_running_effective')}"
    + f" mode={status.get('mode')}"
)
raise SystemExit(0 if healthy else 1)
PY
}

echo "nightly_sync_and_restart=starting at $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "git_pull=starting remote=$REMOTE branch=$BRANCH"
git pull --ff-only "$REMOTE" "$BRANCH"
echo "git_pull=complete"

for ((attempt=1; attempt<=MAX_RESTART_ATTEMPTS; attempt++)); do
  echo "restart_attempt=$attempt/$MAX_RESTART_ATTEMPTS"
  "$ROOT/ops/stack_stop.sh"
  "$ROOT/ops/stack_start.sh"

  for ((check=1; check<=HEALTH_CHECK_ATTEMPTS; check++)); do
    if is_stack_healthy; then
      echo "nightly_sync_and_restart=complete restart_attempt=$attempt health_check=$check"
      exit 0
    fi
    echo "health_check=retry attempt=$check/$HEALTH_CHECK_ATTEMPTS"
    sleep "$HEALTH_CHECK_SLEEP_SECONDS"
  done
done

echo "ERROR: nightly restart health verification failed after $MAX_RESTART_ATTEMPTS attempt(s)"
exit 1