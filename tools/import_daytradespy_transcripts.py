#!/usr/bin/env python3
"""Import authorized DayTradeSPY VTT exports into the research-only corpus."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .build_daytradespy_search_catalog import build_catalog
    from .daytradespy_research_ops import normalize_vtt
else:
    from build_daytradespy_search_catalog import build_catalog
    from daytradespy_research_ops import normalize_vtt


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def import_vtt(post_id: int, vtt_path: Path, root: Path, completeness_pct: int = 100) -> Path:
    """Normalize a VTT supplied from an authorized viewing session."""
    if not 1 <= completeness_pct <= 100:
        raise ValueError("Transcript completeness must be between 1 and 100")
    registry_path = root / "recording_registry.json"
    registry = _read(registry_path)
    entry = next((item for item in registry["recordings"] if int(item["post_id"]) == post_id), None)
    if entry is None:
        raise ValueError(f"Unknown DayTradeSPY post ID: {post_id}")
    cues = normalize_vtt(vtt_path.read_text(encoding="utf-8"), post_id)
    if not cues:
        raise ValueError(f"No WebVTT cues found in {vtt_path}")
    destination = root / "transcripts" / f"{post_id}.json"
    _write(destination, {
        "schema_version": "daytradespy-transcript.v1", "recording_post_id": post_id,
        "source": "AUTHORIZED_BROWSER_TRANSCRIPT_EXPORT", "imported_at": datetime.now(timezone.utc).isoformat(),
        "cue_count": len(cues), "completeness_pct": completeness_pct, "timestamps_preserved": True,
        "speaker_attribution_available": any(cue["speaker"] != "UNKNOWN" for cue in cues),
        "credential_or_session_material_stored": False, "cues": cues,
    })
    entry["transcript"] = {
        "availability": "collected" if completeness_pct == 100 else "partial",
        "completeness_pct": completeness_pct, "path": str(destination),
        "timestamps_preserved": True,
        "speaker_attribution_available": any(cue["speaker"] != "UNKNOWN" for cue in cues),
    }
    if entry["analysis_status"] == "pending":
        entry["analysis_status"] = "transcript_collected"
    registry["generated_at"] = datetime.now(timezone.utc).isoformat()
    _write(registry_path, registry)
    build_catalog(root, root / "search_catalog.sqlite", root / "search_catalog.jsonl")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("post_id", type=int)
    parser.add_argument("vtt", type=Path)
    parser.add_argument("--root", type=Path, default=Path("data/research/daytradespy"))
    parser.add_argument("--completeness-pct", type=int, default=100)
    args = parser.parse_args()
    print(f"Imported transcript: {import_vtt(args.post_id, args.vtt, args.root, args.completeness_pct)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())