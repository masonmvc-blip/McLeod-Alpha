#!/usr/bin/env python3
"""Register authorized-browser coverage measurements as research-only records."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .migrate_daytradespy_legacy_week import record_for
else:
    from migrate_daytradespy_legacy_week import record_for


APRIL_20_24 = (
    (44474, "2026-04-20", 4137, 4049, 179, "1:07:29"),
    (44489, "2026-04-21", 4659, 4656, 219, "1:17:36"),
    (44506, "2026-04-22", 4494, 4483, 219, "1:14:43"),
    (44526, "2026-04-23", 4296, 4268, 212, "1:11:08"),
    (44539, "2026-04-24", 4441, 4425, 193, "1:13:45"),
)


def _load_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": "daytradespy-recording-checkpoint.v1", "recordings": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_checkpoint(path: Path, checkpoint: dict) -> None:
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_path, path)


def register_week(root: Path) -> list[Path]:
    """Create one checkpointed coverage record at a time without retaining transcript text."""
    written: list[Path] = []
    checkpoint_path = root / "recording_checkpoints.json"
    checkpoint = _load_checkpoint(checkpoint_path)
    for post_id, day, duration, coverage_end, cue_count, last_timestamp in APRIL_20_24:
        path = root / "records" / f"{day}.json"
        key = str(post_id)
        if path.exists():
            checkpoint["recordings"].setdefault(key, {
                "day": day,
                "record_path": str(path),
                "status": "PRESERVED_EXISTING_RECORD",
                "checkpointed_at": datetime.now(timezone.utc).isoformat(),
            })
            _write_checkpoint(checkpoint_path, checkpoint)
            continue
        source_url = f"https://daytradespy.com/{post_id}/trading-room-video-recording-april-{day[-2:]}-2026/"
        record = record_for(
            post_id,
            day,
            duration,
            source_url,
            "Authorized browser transcript timing was measured; transcript text and visual trade evidence require separate retained review.",
        )
        coverage = int(coverage_end / duration * 100)
        recording = record["recording"]
        recording["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        recording["reviewer_version"] = "authorized-browser-probe.v1"
        recording["transcript"] = {
            "availability": "PARTIAL_AUTHORIZED_BROWSER_TRANSCRIPT",
            "completeness_pct": coverage,
            "path": "",
            "timestamps_preserved": False,
            "speaker_attribution_available": False,
        }
        recording["transcript_probe"] = {
            "source": "AUTHORIZED_BROWSER_RUNTIME",
            "cue_count": cue_count,
            "first_timestamp": "00:00",
            "last_timestamp": last_timestamp,
            "coverage_end_seconds": coverage_end,
            "raw_transcript_persisted": False,
            "coverage_note": "Measured from the authorized Vimeo transcript panel; visual and trade review remain incomplete.",
        }
        record["evidence_quality"]["transcript_completeness_pct"] = coverage
        record["legacy_evidence"] = {
            "status": "AUTHORIZED_BROWSER_PROBE_ONLY",
            "fact_classification": "SOURCE_OBSERVATION",
        }
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        checkpoint["recordings"][key] = {
            "day": day,
            "record_path": str(path),
            "status": "RECORD_WRITTEN",
            "transcript_completeness_pct": coverage,
            "checkpointed_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_checkpoint(checkpoint_path, checkpoint)
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/research/daytradespy"))
    args = parser.parse_args()
    for path in register_week(args.root):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())