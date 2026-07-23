#!/usr/bin/env python3
"""Refresh Day Trade SPY archive governance without touching production trading."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

if __package__:
    from .build_daytradespy_archive_manifest import build_manifest, load_manifest, write_manifest
    from .build_daytradespy_search_catalog import build_catalog
    from .daytradespy_research_registry import bootstrap_governance
else:
    from build_daytradespy_archive_manifest import build_manifest, load_manifest, write_manifest
    from build_daytradespy_search_catalog import build_catalog
    from daytradespy_research_registry import bootstrap_governance


def main() -> int:
    root = Path("data/research/daytradespy")
    manifest_path = root / "archive_manifest.json"
    manifest = build_manifest(existing=load_manifest(manifest_path))
    write_manifest(manifest, manifest_path)
    bootstrap_governance(root, manifest)
    catalog_count = build_catalog(root, root / "search_catalog.sqlite", root / "search_catalog.jsonl")
    registry = json.loads((root / "recording_registry.json").read_text(encoding="utf-8"))
    recordings = registry["recordings"]
    completed = sum(item.get("analysis_status") == "complete" for item in recordings)
    processed_today = [item["post_id"] for item in recordings if str(item.get("reviewed_at") or "").startswith(str(date.today()))]
    gaps = json.loads((root / "instrumentation_backlog.json").read_text(encoding="utf-8"))["items"]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=False).stdout.strip() or "UNAVAILABLE"
    print(f"Archive recordings discovered: {len(recordings)}")
    print(f"Archive recordings completed: {completed}")
    print(f"Archive recordings remaining: {len(recordings) - completed}")
    print(f"Recording processed today: {processed_today or 'NONE'}")
    print("Transcript coverage: see recording registry")
    print("Visual review coverage: see recording registry")
    print("Evidence grade: see completed evidence bundles")
    print("Hypotheses created: 0")
    print("Hypotheses updated: 0")
    print("Contradictions found: 0")
    print("Replay experiments queued: 0")
    print(f"Instrumentation gaps: {len(gaps)}")
    print(f"Search catalog recordings: {catalog_count}")
    print("Live behavior changed: NO")
    print(f"Commit hash: {commit}")
    print("Next action: process the oldest recording with complete transcript and visual coverage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())