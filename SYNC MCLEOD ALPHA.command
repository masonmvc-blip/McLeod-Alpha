#!/bin/bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

error_exit() {
    local message="$1"
    echo
    echo "ERROR: $message"
    read -r -p "Press Enter to close this window..." _
    exit 1
}

trap 'error_exit "Sync failed on line $LINENO."' ERR

current_branch="$(git branch --show-current)"
if [[ "$current_branch" != "main" ]]; then
    error_exit "SYNC must run on main. Current branch: ${current_branch:-unknown}."
fi

echo "Changed files in McLeod Alpha:"
if [[ -n "$(git status --short -- .)" ]]; then
    git status --short -- .
else
    echo "(none)"
fi

echo
echo "Staging source code, tests, configs, and documentation..."
git add -A -- .

forbidden_staged="$(git diff --cached --name-only -- . | egrep '(^|/)(\.env(\..*)?|token.*|tokens.*|.*credential.*|.*secret.*|.*api.*key.*|.*apikey.*|.*\.log$|.*\.db$|.*\.sqlite3?$|.*\.sqlite-wal$|.*\.sqlite-shm$|.*\.parquet$|.*\.feather$|.*\.h5$|.*\.hdf5$|.*\.npy$|.*\.npz$|^reports/|^output/|^screenshots/|^logs/|^data/(market_data|market-data|raw_market_data|historical|history|ticks|quotes|bars|cache)/)' || true)"
if [[ -n "$forbidden_staged" ]]; then
    echo
    echo "Refusing to commit forbidden staged files:"
    printf '%s\n' "$forbidden_staged"
    git reset -- .
    error_exit "One or more secrets, logs, databases, screenshots, or market-data files were staged."
fi

echo
echo "Staged files:"
if [[ -n "$(git diff --cached --name-only -- .)" ]]; then
    git diff --cached --name-only -- .
else
    echo "(none)"
fi

read -r -p "Short commit message: " commit_message
if [[ -z "${commit_message// }" ]]; then
    git reset -- .
    error_exit "Commit message cannot be empty."
fi

echo
echo "Committing..."
git commit -m "$commit_message"

echo
echo "Fetching and rebasing main..."
git fetch origin main
git pull --rebase origin main

echo
echo "Pushing to origin main..."
git push origin main

echo
echo "SUCCESS: Synced McLeod Alpha to GitHub."
