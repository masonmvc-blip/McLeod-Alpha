#!/usr/bin/env bash
set -euo pipefail

TARGET_PATH="${1:-$(pwd)}"
EXPECTED_BASENAME="${MCLEOD_CANONICAL_REPO_BASENAME:-McLeod-Alpha-New}"

TARGET_REAL="$(cd "$TARGET_PATH" && pwd)"
TARGET_BASE="$(basename "$TARGET_REAL")"

if [[ "$TARGET_BASE" != "$EXPECTED_BASENAME" ]]; then
  echo "ERROR: canonical workflow requires repo folder '$EXPECTED_BASENAME'"
  echo "current=$TARGET_REAL"
  echo "hint: cd ~/Documents/GitHub/$EXPECTED_BASENAME"
  exit 1
fi
