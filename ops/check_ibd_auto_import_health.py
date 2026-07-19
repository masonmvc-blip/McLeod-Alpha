#!/usr/bin/env python3
"""Health check for IBD auto-import freshness."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "ibd_auto_import_state.json"
DEST_PATH = ROOT / "data" / "ibd_rankings_manual.csv"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_iso(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate IBD auto-import freshness.")
    parser.add_argument("--max-age-hours", type=int, default=30)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    issues: list[str] = []
    state = _load_json(STATE_PATH) if STATE_PATH.exists() else {}

    if not DEST_PATH.exists():
        issues.append("ibd_destination_missing")

    imported_at = _parse_iso(str(state.get("last_imported_at", "")))
    if imported_at is None:
        issues.append("last_imported_at_missing_or_invalid")
    else:
        now = datetime.now(imported_at.tzinfo) if imported_at.tzinfo else datetime.now()
        age_hours = (now - imported_at).total_seconds() / 3600.0
        if age_hours > args.max_age_hours:
            issues.append("ibd_import_stale")

    rows = int(state.get("last_row_count", 0) or 0)
    if rows <= 0:
        issues.append("ibd_row_count_invalid")

    if not args.quiet:
        print("IBD Auto Import Health")
        print(f"state: {STATE_PATH}")
        print(f"destination: {DEST_PATH}")
        print(f"last_imported_at: {state.get('last_imported_at', 'n/a')}")
        print(f"last_source_path: {state.get('last_source_path', 'n/a')}")
        print(f"last_row_count: {rows}")
        print(f"issues: {','.join(issues) if issues else 'none'}")

    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
