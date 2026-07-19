#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${MCLEOD_ROOT:-$ROOT_DEFAULT}"
REMOTE="${MCLEOD_GIT_REMOTE:-origin}"
BRANCH="${MCLEOD_GIT_BRANCH:-main}"
INTERVAL_SECONDS="${MCLEOD_AUTO_PUBLISH_POLL_SECONDS:-3}"
DEBOUNCE_SECONDS="${MCLEOD_AUTO_PUBLISH_DEBOUNCE_SECONDS:-3}"
STATE_FILE="${MCLEOD_AUTO_PUBLISH_STATE_FILE:-$ROOT/data/auto_publish_last_state.txt}"

cd "$ROOT"

publish_changes() {
  local before after remote_head
  before="$(git status --porcelain --untracked-files=all)"
  [[ -z "$before" ]] && return 0

  sleep "$DEBOUNCE_SECONDS"
  after="$(git status --porcelain --untracked-files=all)"
  [[ "$before" == "$after" ]] || return 0

  git rm --cached --ignore-unmatch .bot_pid >/dev/null 2>&1 || true
  git add -A -- . ':(exclude)artifacts/test_reports/**'
  if git diff --cached --quiet; then
    return 0
  fi

  git commit -m "Auto-save workspace changes $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  git fetch "$REMOTE" "$BRANCH"
  if ! git rebase "$REMOTE/$BRANCH"; then
    echo "auto_publish=CONFLICT: resolve the rebase; no work was overwritten" >&2
    return 1
  fi
  git push "$REMOTE" "$BRANCH"

  remote_head="$(git ls-remote "$REMOTE" "refs/heads/$BRANCH" | awk '{print $1}')"
  if [[ "$(git rev-parse HEAD)" != "$remote_head" ]]; then
    echo "auto_publish=FAILED: remote SHA verification failed" >&2
    return 1
  fi
  echo "auto_publish=OK sha=$remote_head"
}

mkdir -p "$(dirname "$STATE_FILE")"
echo "auto_publish_watch=starting root=$ROOT interval=$INTERVAL_SECONDS debounce=$DEBOUNCE_SECONDS"

while true; do
  fingerprint="$(git status --porcelain --untracked-files=all | sha256sum | awk '{print $1}')"
  previous="$(cat "$STATE_FILE" 2>/dev/null || true)"
  if [[ "$fingerprint" != "$previous" ]]; then
    if publish_changes; then
      git status --porcelain --untracked-files=all | sha256sum | awk '{print $1}' > "$STATE_FILE"
    fi
  fi
  sleep "$INTERVAL_SECONDS"
done