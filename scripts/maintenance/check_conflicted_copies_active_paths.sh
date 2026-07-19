#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

hits=$(find . -type f -iname '*conflicted copy*' \
  -not -path './archive/*' \
  -not -path './backups/*' \
  -not -path './.venv/*' \
  -not -path './venv/*' \
  | sort || true)

if [[ -n "$hits" ]]; then
  echo "Found conflicted-copy files in active paths:"
  echo "$hits"
  exit 1
fi

echo "No conflicted-copy files found in active paths."
