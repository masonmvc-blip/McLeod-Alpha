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

# Preserve any local edits, then hard-sync to remote branch to prevent stale deploys.
if [[ -n "$(git status --porcelain)" ]]; then
	STASH_NAME="auto-promote-$(date +%Y%m%d-%H%M%S)"
	git stash push -u -m "$STASH_NAME" || true
	echo "stashed_local_changes=$STASH_NAME"
fi

git fetch "$REMOTE"
git checkout "$BRANCH"
git reset --hard "$REMOTE/$BRANCH"

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
