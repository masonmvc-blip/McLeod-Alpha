"""Deterministic timeline index generation."""

from __future__ import annotations

from typing import Any, Iterable


def build_timeline(snapshot_records: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    rows = [
        {
            "snapshot_id": str(record["snapshot_id"]),
            "snapshot_date": str(record["snapshot_date"]),
            "snapshot_hash": str(record["snapshot_hash"]),
            "snapshot_path": f"snapshots/{record['snapshot_id']}.json",
        }
        for record in snapshot_records
    ]
    return sorted(rows, key=lambda row: (row["snapshot_date"], row["snapshot_id"]))