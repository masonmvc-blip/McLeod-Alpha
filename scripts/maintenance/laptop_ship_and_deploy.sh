#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
REMOTE="${MCLEOD_GIT_REMOTE:-origin}"
BRANCH="${MCLEOD_GIT_BRANCH:-main}"
CANONICAL_URL="${MCLEOD_CANONICAL_CONTROL_CENTER_URL:-https://masons-imac.tailb88bd7.ts.net}"
TRIGGER_GOLIVE=1
COMMIT_MESSAGE=""

usage() {
  cat <<'USAGE'
Usage: laptop_ship_and_deploy.sh [-m "commit message"] [--no-go-live]

Behavior:
- Commits local changes (if any)
- Pushes to remote branch
- Triggers canonical Control Center /api/go-live (unless --no-go-live)

Environment overrides:
- MCLEOD_ROOT
- MCLEOD_GIT_REMOTE
- MCLEOD_GIT_BRANCH
- MCLEOD_CANONICAL_CONTROL_CENTER_URL
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--message)
      shift
      COMMIT_MESSAGE="${1:-}"
      ;;
    --no-go-live)
      TRIGGER_GOLIVE=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
  shift
done

cd "$ROOT"

if [[ ! -d .git ]]; then
  echo "ERROR: not a git repo: $ROOT" >&2
  exit 1
fi

if [[ -z "$COMMIT_MESSAGE" ]]; then
  COMMIT_MESSAGE="Laptop ship $(date '+%Y-%m-%d %H:%M:%S %Z')"
fi

echo "ship_root=$ROOT"
echo "ship_remote=$REMOTE ship_branch=$BRANCH"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ship_changes=detected"
  git add -A
  git commit -m "$COMMIT_MESSAGE"
else
  echo "ship_changes=none"
fi

LOCAL_HEAD="$(git rev-parse HEAD)"
echo "ship_local_head=$LOCAL_HEAD"

git push "$REMOTE" "$BRANCH"
echo "ship_push=ok"

if [[ "$TRIGGER_GOLIVE" != "1" ]]; then
  echo "ship_trigger_golive=skipped"
  exit 0
fi

GO_LIVE_URL="${CANONICAL_URL%/}/api/go-live"
STATUS_URL="${CANONICAL_URL%/}/api/status"
START_URL="${CANONICAL_URL%/}/api/start"

echo "ship_trigger_golive=url:$GO_LIVE_URL"
HTTP_CODE="$(curl -ksS -o /tmp/mcleod_golive_response.json -w '%{http_code}' -X POST "$GO_LIVE_URL" || true)"

if [[ "$HTTP_CODE" == "200" ]]; then
  echo "ship_trigger_golive=accepted"
  python3 - <<'PY' /tmp/mcleod_golive_response.json
import json
import sys

path = sys.argv[1]
try:
    payload = json.loads(open(path, "r", encoding="utf-8").read())
except Exception:
    payload = {}

print("go_live_status=" + str(payload.get("status") or "unknown"))
print("go_live_message=" + str(payload.get("message") or ""))
PY
else
  echo "ship_trigger_golive=failed http_code=$HTTP_CODE"
  echo "ship_trigger_fallback=url:$START_URL"
  START_HTTP_CODE="$(curl -ksS -o /tmp/mcleod_start_response.json -w '%{http_code}' -X POST "$START_URL" || true)"
  if [[ "$START_HTTP_CODE" == "200" ]]; then
    echo "ship_trigger_fallback=start_api_accepted"
    python3 - <<'PY' /tmp/mcleod_start_response.json
import json
import sys

path = sys.argv[1]
try:
    payload = json.loads(open(path, "r", encoding="utf-8").read())
except Exception:
    payload = {}

print("start_api_status=" + str(payload.get("status") or "unknown"))
print("start_api_message=" + str(payload.get("message") or ""))
PY
  else
    echo "ship_trigger_fallback=failed http_code=$START_HTTP_CODE"
    echo "ship_note=desktop watcher will still deploy on next poll if canonical autodeploy is running"
  fi
fi

echo "ship_status_probe=url:$STATUS_URL"
curl -ksS "$STATUS_URL" | python3 - <<'PY'
import json
import sys

try:
    payload = json.load(sys.stdin)
except Exception:
    payload = {}

fp = payload.get("runtime_fingerprint") or {}
print("runtime_host=" + str(fp.get("hostname") or "unknown"))
print("runtime_repo=" + str(fp.get("project_root") or "unknown"))
print("bot_running_effective=" + str(payload.get("bot_running_effective")))
print("parity_state=" + str(payload.get("parity_state") or "UNKNOWN"))
print("parity_block_start=" + str(payload.get("parity_block_start")))
print("control_center_sha256=" + str(fp.get("control_center_sha256") or ""))
PY

echo "ship_complete=1"
