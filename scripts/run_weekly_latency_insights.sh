#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DAYS="${1:-7}"

cd "$ROOT"
python3 scripts/weekly_latency_insights.py --days "$DAYS"
