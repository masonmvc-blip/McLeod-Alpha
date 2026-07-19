"""Deterministic construction of immutable historical replay datasets."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Any, Iterable, Mapping

from .dataset_index import build_timeline
from .dataset_manifest import create_manifest, dataset_content_hash
from .dataset_schema import DatasetMetadata, SCHEMA_VERSION, canonical_json_bytes, hash_bytes, normalize_json, parse_date
from .dataset_validator import DatasetValidator


class DatasetBuilder:
    """Build a complete historical world from date-bounded raw snapshot input."""

    def build(
        self,
        *,
        output_dir: Path | str,
        dataset_id: str,
        dataset_name: str,
        market: str,
        snapshots: Iterable[Mapping[str, Any]],
        expected_dates: Iterable[str] | None = None,
    ) -> Path:
        target = Path(output_dir)
        normalized = [self._normalize_snapshot(snapshot) for snapshot in snapshots]
        normalized.sort(key=lambda row: (row["snapshot_date"], row["snapshot_id"]))
        if not normalized:
            raise ValueError("At least one snapshot is required")
        if not str(dataset_id).strip() or not str(dataset_name).strip() or not str(market).strip():
            raise ValueError("dataset_id, dataset_name, and market must be non-empty")

        expected = tuple(sorted({str(value) for value in (expected_dates or [row["snapshot_date"] for row in normalized])}))
        for value in expected:
            parse_date(value, field_name="expected_dates")

        snapshot_hashes = {row["snapshot_id"]: hash_bytes(canonical_json_bytes(row)) for row in normalized}
        metadata_without_hash = {
            "dataset_id": str(dataset_id),
            "dataset_name": str(dataset_name),
            "market": str(market),
            "start_date": normalized[0]["snapshot_date"],
            "end_date": normalized[-1]["snapshot_date"],
            "snapshot_count": len(normalized),
            "schema_version": SCHEMA_VERSION,
            "expected_dates": list(expected),
        }
        content_hash = dataset_content_hash(metadata_without_hash=metadata_without_hash, snapshot_hashes=snapshot_hashes)
        metadata = DatasetMetadata(content_hash=content_hash, **metadata_without_hash)
        manifest = create_manifest(dataset_id=metadata.dataset_id, content_hash=content_hash, snapshot_hashes=snapshot_hashes)

        with TemporaryDirectory(prefix="mcleod_dataset_") as temporary_root:
            temporary_dir = Path(temporary_root) / "dataset"
            snapshots_dir = temporary_dir / "snapshots"
            timeline_dir = temporary_dir / "timeline"
            snapshots_dir.mkdir(parents=True)
            timeline_dir.mkdir(parents=True)
            for row in normalized:
                self._write_json(snapshots_dir / f"{row['snapshot_id']}.json", row)
            self._write_json(timeline_dir / "index.json", build_timeline([{**row, "snapshot_hash": snapshot_hashes[row["snapshot_id"]]} for row in normalized]))
            self._write_json(temporary_dir / "metadata.json", metadata.to_dict())
            self._write_json(temporary_dir / "manifest.json", manifest.to_dict())
            DatasetValidator().validate(temporary_dir)
            self._publish_immutable(temporary_dir, target)
        return target

    @staticmethod
    def _normalize_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
        row = normalize_json(dict(snapshot))
        snapshot_id = str(row.get("snapshot_id") or "").strip()
        snapshot_date = str(row.get("snapshot_date") or "").strip()
        if not snapshot_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in snapshot_id):
            raise ValueError("snapshot_id must be non-empty and filesystem-safe")
        parse_date(snapshot_date, field_name="snapshot_date")
        row["snapshot_id"] = snapshot_id
        row["snapshot_date"] = snapshot_date
        return row

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_bytes(canonical_json_bytes(payload))

    @staticmethod
    def _publish_immutable(source: Path, target: Path) -> None:
        if target.exists():
            existing = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
            candidate = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
            if existing != candidate:
                raise FileExistsError(f"Dataset path already exists with different content: {target}")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.parent / f".{target.name}.staging"
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(source, staging)
        os.replace(staging, target)