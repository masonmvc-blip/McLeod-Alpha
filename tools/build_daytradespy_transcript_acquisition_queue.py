#!/usr/bin/env python3
"""Build an authorized transcript and visual-review acquisition queue by archive year."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_queue(registry: dict[str, Any], year: str) -> dict[str, Any]:
    recordings = [
        item for item in registry["recordings"]
        if item["recording_date"].startswith(f"{year}-") and item["analysis_status"] == "pending"
    ]
    recordings.sort(key=lambda item: (item["recording_date"], item["post_id"]), reverse=True)
    return {
        "schema_version": "daytradespy-transcript-acquisition-queue.v1",
        "year": year,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Authorized source acquisition only; no video, credential, cookie, token, or signed URL is stored.",
        "required_before_research_completion": [
            "complete timestamped VTT transcript export",
            "visual-review notes with chart timestamps",
            "recording-end coverage confirmation",
        ],
        "recordings": [
            {
                "priority": index + 1,
                "post_id": item["post_id"],
                "recording_date": item["recording_date"],
                "title": item["title"],
                "source_url": item["source_url"],
                "acquisition_status": "PENDING_AUTHORIZED_ACCESS",
                "transcript_import_command": f"python3 tools/import_daytradespy_transcripts.py {item['post_id']} <authorized-export.vtt>",
                "visual_review_status": "PENDING_AUTHORIZED_ACCESS",
                "research_status": "NOT_REVIEWED",
            }
            for index, item in enumerate(recordings)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", default="2025")
    parser.add_argument("--registry", type=Path, default=Path("data/research/daytradespy/recording_registry.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    output = args.output or Path(f"data/research/daytradespy/transcript_acquisition_queue_{args.year}.json")
    queue = build_queue(registry, args.year)
    output.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{output}: {len(queue['recordings'])} recordings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())