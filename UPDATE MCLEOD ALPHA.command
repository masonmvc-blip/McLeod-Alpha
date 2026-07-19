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

trap 'error_exit "Update failed on line $LINENO."' ERR

echo "Fetching remote changes..."
git fetch origin main

if [[ -n "$(git status --porcelain -- .)" ]]; then
    echo
    echo "Uncommitted local changes detected in McLeod Alpha:"
    git status --short -- .
    error_exit "Refusing to continue with local changes."
fi

echo "Pulling latest main..."
git pull --ff-only origin main

echo
echo "SUCCESS: McLeod Alpha is up to date."
