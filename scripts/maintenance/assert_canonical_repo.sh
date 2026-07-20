#!/usr/bin/env bash
set -euo pipefail

TARGET_PATH="${1:-$(pwd)}"
EXPECTED_BASENAME="${MCLEOD_CANONICAL_REPO_BASENAME:-McLeod-Alpha-New}"
EXPECTED_PATH="${MCLEOD_CANONICAL_REPO_PATH:-$HOME/GitHub/$EXPECTED_BASENAME}"

TARGET_REAL="$(cd "$TARGET_PATH" && pwd)"
EXPECTED_REAL="$(cd "$EXPECTED_PATH" && pwd)"

if [[ "$TARGET_REAL" != "$EXPECTED_REAL" ]]; then
  echo "ERROR: canonical workflow requires the configured repository path"
  echo "current=$TARGET_REAL"
  echo "required=$EXPECTED_REAL"
  exit 1
fi
