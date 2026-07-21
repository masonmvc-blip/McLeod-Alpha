#!/usr/bin/env bash
set -euo pipefail

# Repository hygiene checker: flags root-level clutter and doc sprawl.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

issue_count=0

echo
echo "[Root backup files]"
backup_hits=$(find . -maxdepth 1 -type f \( -name '*backup*' -o -name '*.bak' \) | sed 's#^./##' | sort || true)
if [[ -n "$backup_hits" ]]; then
  echo "$backup_hits"
  count=$(echo "$backup_hits" | wc -l | tr -d ' ')
  issue_count=$((issue_count + count))
else
  echo "none"
fi

echo
echo "[Root ad-hoc fix scripts]"
fix_hits=$(find . -maxdepth 1 -type f -name 'fix_*.py' | sed 's#^./##' | sort || true)
if [[ -n "$fix_hits" ]]; then
  echo "$fix_hits"
  count=$(echo "$fix_hits" | wc -l | tr -d ' ')
  issue_count=$((issue_count + count))
else
  echo "none"
fi

echo
echo "[Root conflicted copies]"
conflict_hits=$(find . -maxdepth 1 -type f -name '*conflicted copy*' | sed 's#^./##' | sort || true)
if [[ -n "$conflict_hits" ]]; then
  echo "$conflict_hits"
  count=$(echo "$conflict_hits" | wc -l | tr -d ' ')
  issue_count=$((issue_count + count))
else
  echo "none"
fi

echo

echo "[Research summary docs in root]"
research_docs=$(find . -maxdepth 1 -type f -name 'RESEARCH_ENGINE*.md' | sed 's#^./##' | sort || true)
if [[ -n "$research_docs" ]]; then
  echo "$research_docs"
  count=$(echo "$research_docs" | wc -l | tr -d ' ')
  if (( count > 2 )); then
    echo "warning: keep only FINAL_STATUS and QUICKREF in root"
    issue_count=$((issue_count + count - 2))
  fi
else
  echo "none"
fi

echo

echo "[Environment directories]"
if [[ -d .venv && -d venv ]]; then
  echo "warning: both .venv and venv exist; standardize on one"
  issue_count=$((issue_count + 1))
else
  echo "ok"
fi

echo
echo "[Legacy monitor scripts in root]"
legacy_hits=$(find . -maxdepth 1 -type f \( -name 'phase1_monitor.py' -o -name 'phase2_monitor.py' \) | sed 's#^./##' | sort || true)
if [[ -n "$legacy_hits" ]]; then
  echo "$legacy_hits"
  count=$(echo "$legacy_hits" | wc -l | tr -d ' ')
  issue_count=$((issue_count + count))
else
  echo "none"
fi

echo
if (( issue_count > 0 )); then
  echo "Hygiene check failed with $issue_count issue(s)."
  exit 1
fi

echo
echo "[Active path conflicted-copy prevention]"
"$ROOT_DIR/scripts/maintenance/check_conflicted_copies_active_paths.sh"

echo
echo "[Cockpit runtime parity]"
if [[ -n "${MCLEOD_COCKPIT_URL_A:-}" && -n "${MCLEOD_COCKPIT_URL_B:-}" ]]; then
  "$ROOT_DIR/scripts/maintenance/check_cockpit_parity.sh"
else
  echo "skipped (set MCLEOD_COCKPIT_URL_A and MCLEOD_COCKPIT_URL_B)"
fi

echo "Hygiene check passed."
