#!/usr/bin/env python3
"""Modernize only April 2026 Day Trade SPY entries that still have legacy reports."""

from __future__ import annotations

import json
from pathlib import Path

if __package__:
    from .daytradespy_record_processor import register_record
    from .daytradespy_research_ops import aggregate_record, write_output_bundle
    from .migrate_daytradespy_legacy_week import record_for
else:
    from daytradespy_record_processor import register_record
    from daytradespy_research_ops import aggregate_record, write_output_bundle
    from migrate_daytradespy_legacy_week import record_for


POST_IDS = (44232, 44269, 44288, 44300, 44314, 44334, 44369, 44382, 44411, 44434, 44458)
OBSERVATION = (
    "A legacy report exists for this recording, but its narrative has not been reverified "
    "against exportable transcript, visual, market, or execution evidence."
)


def main() -> int:
    root = Path("data/research/daytradespy")
    registry_path = root / "recording_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = {int(item["post_id"]): item for item in registry["recordings"]}
    written = []
    for post_id in POST_IDS:
        entry = entries[post_id]
        if entry.get("machine_record_path"):
            continue
        day = str(entry["recording_date"])[:10]
        report_path = Path(str(entry["report_path"]))
        if not report_path.is_file():
            raise FileNotFoundError(f"Missing legacy report for post {post_id}: {report_path}")
        record = record_for(post_id, day, None, str(entry["source_url"]), OBSERVATION)
        record["recording"]["title"] = str(entry["title"])
        record["recording"]["transcript"]["availability"] = "LEGACY_REPORT_NO_EXPORT"
        record["evidence_quality"]["overall_grade"] = "LEGACY_SYNTHESIS_ONLY"
        record["instrumentation_gaps"] = [
            "Exportable transcript or timestamped observation log",
            "Visual review",
            "Timestamped underlying bars",
            "Option bid, ask, mark, MFE, and MAE telemetry",
            "Canonical ledger mapping",
        ]
        record_path = root / "records" / f"{day}.json"
        record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        write_output_bundle(record, root / "output")
        aggregate_record(record, root)
        register_record(record_path, registry_path)
        written.append(record_path)
    print(f"Modernized {len(written)} April 2026 legacy records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())