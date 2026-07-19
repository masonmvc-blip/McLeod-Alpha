#!/usr/bin/env python3
"""Targeted gap closer for Morning CIO report blockers.

Reads the latest Morning CIO JSON/TXT artifacts and runs only the refresh modules
needed for currently reported blockers.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Set


ROOT = Path(__file__).resolve().parent.parent
REPORT_JSON = ROOT / "data" / "reports" / "morning_cio_email" / "latest_morning_cio_report.json"
REPORT_TXT = ROOT / "data" / "reports" / "morning_cio_email" / "latest_morning_cio_report.txt"


FIELD_TO_MODULES: Dict[str, List[str]] = {
    "business_quality": ["engine/research_engine.py", "engine/intelligence_engine.py"],
    "valuation": ["engine/research_engine.py", "engine/intelligence_engine.py"],
    "expected_alpha": ["engine/research_engine.py", "engine/intelligence_engine.py"],
    "expected_2yr_cagr": ["engine/research_engine.py", "engine/intelligence_engine.py"],
    "expected_10yr_cagr": ["engine/research_engine.py", "engine/intelligence_engine.py"],
    "thesis_health": ["engine/research_engine.py", "engine/intelligence_engine.py"],
    "sync_timestamp": ["portfolio_sync.py"],
    "recent filings and headlines": ["engine/data_sources/sec_source.py"],
}


def _python_exec() -> str:
    venv = ROOT / "venv" / "bin" / "python"
    alt = ROOT / ".venv" / "bin" / "python"
    if venv.exists():
        return str(venv)
    if alt.exists():
        return str(alt)
    return "python3"


def _extract_blocking_fields() -> Set[str]:
    fields: Set[str] = set()
    if REPORT_TXT.exists():
        for line in REPORT_TXT.read_text(encoding="utf-8").splitlines():
            if "impact BLOCKS_RECOMMENDATION" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                candidate = parts[1].lstrip("-").strip()
                if candidate:
                    fields.add(candidate)
    return fields


def build_run_list(blocking_fields: Set[str]) -> List[str]:
    modules: List[str] = []
    seen = set()
    for field in sorted(blocking_fields):
        for module in FIELD_TO_MODULES.get(field, []):
            if module not in seen:
                seen.add(module)
                modules.append(module)
    return modules


def main() -> int:
    parser = argparse.ArgumentParser(description="Run targeted module refreshes for Morning CIO blockers.")
    parser.add_argument("--apply", action="store_true", help="Execute module runs. Without this flag, only print the plan.")
    args = parser.parse_args()

    if not REPORT_JSON.exists() and not REPORT_TXT.exists():
        print("No Morning CIO report artifacts found. Run the report first.")
        return 1

    blocking_fields = _extract_blocking_fields()
    if not blocking_fields:
        print("No blocking fields detected in latest report.")
        return 0

    run_list = build_run_list(blocking_fields)
    print("Blocking fields:")
    for field in sorted(blocking_fields):
        print(f"- {field}")

    print("\nPlanned module runs:")
    for mod in run_list:
        print(f"- {mod}")

    if not args.apply:
        print("\nDry run only. Use --apply to execute.")
        return 0

    py = _python_exec()
    failures = 0
    for mod in run_list:
        print(f"\nRunning: {mod}")
        result = subprocess.run([py, mod], cwd=str(ROOT), check=False)
        if result.returncode != 0:
            failures += 1
            print(f"FAILED: {mod} (exit {result.returncode})")

    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
