#!/usr/bin/env python3
"""Convert all remaining 2026 DayTradeSPY legacy reports into evidence records."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

if __package__:
    from .migrate_daytradespy_legacy_week import record_for
else:
    from migrate_daytradespy_legacy_week import record_for


REPORT_NAME = re.compile(r"^(2026-\d{2}-\d{2})_daytradespy_trading_room_research\.md$")


def _observation(report: Path) -> str:
    """Use one bounded, pre-existing observation; raw transcripts are not inferred."""
    for line in report.read_text(encoding="utf-8").splitlines():
        if line.startswith("- "):
            return line[2:].strip()[:500]
    return "Legacy DayTradeSPY report is available; detailed source evidence requires authorized transcript import."


def migrate(root: Path, reports: Path) -> list[Path]:
    registry = json.loads((root / "recording_registry.json").read_text(encoding="utf-8"))
    outputs: list[Path] = []
    for item in registry["recordings"]:
        if item["analysis_status"] != "legacy_report_available":
            continue
        report = Path(item["report_path"])
        match = REPORT_NAME.match(report.name)
        if match is None or not report.exists():
            continue
        day = item["recording_date"][:10]
        record = record_for(
            int(item["post_id"]), day, item.get("duration_seconds") or 0,
            str(item["source_url"]), _observation(report),
        )
        output = root / "records" / f"{day}-{item['post_id']}.json"
        output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outputs.append(output)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/research/daytradespy"))
    parser.add_argument("--reports", type=Path, default=Path("docs/research"))
    args = parser.parse_args()
    outputs = migrate(args.root, args.reports)
    print(f"Migrated {len(outputs)} legacy DayTradeSPY reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())