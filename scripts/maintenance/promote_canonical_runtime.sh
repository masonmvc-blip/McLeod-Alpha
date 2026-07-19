#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
REMOTE="${MCLEOD_GIT_REMOTE:-origin}"
BRANCH="${MCLEOD_GIT_BRANCH:-main}"
BASE_URL="${MCLEOD_BASE_URL:-http://127.0.0.1:5001}"

cd "$ROOT"
"$ROOT/scripts/maintenance/assert_canonical_repo.sh" "$ROOT"

echo "Promote canonical runtime"
echo "root=$ROOT"
echo "remote=$REMOTE branch=$BRANCH"

if [[ -n "$(git status --porcelain)" ]]; then
	echo "ERROR: canonical worktree is dirty; refusing to stash, reset, or promote unpublished changes"
	echo "Run scripts/maintenance/laptop_ship_and_deploy.sh from the machine containing the changes."
	git status --short
	exit 2
fi

git fetch "$REMOTE"
git merge --ff-only "$REMOTE/$BRANCH"

MCLEOD_REQUIRED_ACCOUNT_MODE="${MCLEOD_REQUIRED_ACCOUNT_MODE:-live}" \
MCLEOD_REQUIRED_SCHWAB_CALLBACK_URL="${MCLEOD_REQUIRED_SCHWAB_CALLBACK_URL:-https://127.0.0.1}" \
MCLEOD_REQUIRED_REDIRECT_NONCANONICAL_CONTROL_CENTER="${MCLEOD_REQUIRED_REDIRECT_NONCANONICAL_CONTROL_CENTER:-0}" \
RUN_BACKGROUND=1 "$ROOT/scripts/maintenance/start_control_center_guarded.sh"

for _ in {1..30}; do
	if curl -sf "$BASE_URL/api/status" >/dev/null 2>&1; then
		break
	fi
	sleep 1
done

curl -sS -X POST "$BASE_URL/api/parity/baseline"
echo
curl -sS -X POST "$BASE_URL/api/start"
echo
curl -sS "$BASE_URL/api/status"
