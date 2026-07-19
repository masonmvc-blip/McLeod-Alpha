"""Fail-closed integrity and anti-lookahead validation for replay datasets."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import json
from typing import Any

from .dataset_manifest import dataset_content_hash
from .dataset_schema import CREATION_VERSION, SCHEMA_VERSION, canonical_json_bytes, hash_bytes, parse_date


class DatasetValidationError(ValueError):
    """Raised when an immutable dataset violates its schema or integrity contract."""


class DatasetValidator:
    def validate(self, dataset_dir: Path | str) -> None:
        root = Path(dataset_dir)
        metadata = self._read_json(root / "metadata.json")
        manifest = self._read_json(root / "manifest.json")
        timeline = self._read_json(root / "timeline" / "index.json")
        self._validate_metadata(metadata)
        self._validate_manifest(metadata, manifest)
        if not isinstance(timeline, list):
            raise DatasetValidationError("timeline/index.json must be an array")

        timeline_ids = []
        timeline_hashes = []
        for record in timeline:
            if not isinstance(record, dict):
                raise DatasetValidationError("timeline record must be an object")
            timeline_ids.append(str(record.get("snapshot_id") or ""))
            timeline_hashes.append(str(record.get("snapshot_hash") or ""))
        if len(timeline_ids) != len(set(timeline_ids)):
            raise DatasetValidationError("duplicate snapshot ID")
        if len(timeline_hashes) != len(set(timeline_hashes)):
            raise DatasetValidationError("duplicate snapshot hash")

        seen_ids: set[str] = set()
        seen_hashes: set[str] = set()
        timeline_dates: list[str] = []
        snapshot_hashes: dict[str, str] = {}
        previous_key: tuple[str, str] | None = None
        for record in timeline:
            if not isinstance(record, dict):
                raise DatasetValidationError("timeline record must be an object")
            snapshot_id = str(record.get("snapshot_id") or "")
            snapshot_date = str(record.get("snapshot_date") or "")
            listed_hash = str(record.get("snapshot_hash") or "")
            key = (snapshot_date, snapshot_id)
            if previous_key is not None and key <= previous_key:
                raise DatasetValidationError("timeline records must be in strict chronological order")
            previous_key = key
            if snapshot_id in seen_ids:
                raise DatasetValidationError(f"duplicate snapshot ID: {snapshot_id}")
            if listed_hash in seen_hashes:
                raise DatasetValidationError(f"duplicate snapshot hash: {listed_hash}")
            seen_ids.add(snapshot_id)
            seen_hashes.add(listed_hash)
            timeline_dates.append(snapshot_date)
            snapshot = self._read_json(root / "snapshots" / f"{snapshot_id}.json")
            if snapshot.get("snapshot_id") != snapshot_id or snapshot.get("snapshot_date") != snapshot_date:
                raise DatasetValidationError(f"timeline mismatch for snapshot: {snapshot_id}")
            actual_hash = hash_bytes(canonical_json_bytes(snapshot))
            if actual_hash != listed_hash:
                raise DatasetValidationError(f"snapshot content hash mismatch: {snapshot_id}")
            self._validate_no_lookahead(snapshot, as_of=parse_date(snapshot_date, field_name="snapshot_date"), path=f"snapshot[{snapshot_id}]")
            snapshot_hashes[snapshot_id] = actual_hash

        if int(metadata["snapshot_count"]) != len(timeline):
            raise DatasetValidationError("metadata snapshot_count does not match timeline")
        if list(metadata.get("expected_dates") or []) != timeline_dates:
            raise DatasetValidationError("missing or unexpected snapshot dates")
        if manifest.get("snapshot_hashes") != dict(sorted(snapshot_hashes.items())):
            raise DatasetValidationError("manifest snapshot hashes do not match snapshots")
        metadata_without_hash = dict(metadata)
        metadata_without_hash.pop("content_hash", None)
        expected_content_hash = dataset_content_hash(metadata_without_hash=metadata_without_hash, snapshot_hashes=snapshot_hashes)
        if metadata.get("content_hash") != expected_content_hash or manifest.get("content_hash") != expected_content_hash:
            raise DatasetValidationError("dataset content hash mismatch")

    @staticmethod
    def _read_json(path: Path) -> Any:
        if not path.is_file():
            raise DatasetValidationError(f"required dataset file is missing: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DatasetValidationError(f"invalid JSON: {path}") from exc

    @staticmethod
    def _validate_metadata(metadata: Any) -> None:
        if not isinstance(metadata, dict):
            raise DatasetValidationError("metadata.json must be an object")
        required = {"dataset_id", "dataset_name", "market", "start_date", "end_date", "snapshot_count", "schema_version", "content_hash"}
        missing = required - set(metadata)
        if missing:
            raise DatasetValidationError(f"metadata missing fields: {', '.join(sorted(missing))}")
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise DatasetValidationError("unsupported schema version")
        start = parse_date(metadata["start_date"], field_name="start_date")
        end = parse_date(metadata["end_date"], field_name="end_date")
        if end < start or int(metadata["snapshot_count"]) <= 0:
            raise DatasetValidationError("invalid metadata date range or snapshot count")

    @staticmethod
    def _validate_manifest(metadata: dict[str, Any], manifest: Any) -> None:
        if not isinstance(manifest, dict):
            raise DatasetValidationError("manifest.json must be an object")
        if manifest.get("dataset_id") != metadata.get("dataset_id"):
            raise DatasetValidationError("manifest dataset_id does not match metadata")
        if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("creation_version") != CREATION_VERSION:
            raise DatasetValidationError("manifest version mismatch")
        if not isinstance(manifest.get("snapshot_hashes"), dict):
            raise DatasetValidationError("manifest snapshot_hashes must be an object")

    def _validate_no_lookahead(self, value: Any, *, as_of: date, path: str) -> None:
        if isinstance(value, dict):
            lower = {str(key).lower(): key for key in value}
            for marker in ("future", "is_future", "lookahead"):
                if marker in lower and bool(value[lower[marker]]):
                    raise DatasetValidationError(f"lookahead marker at {path}.{lower[marker]}")
            for key in sorted(value, key=str):
                self._validate_no_lookahead(value[key], as_of=as_of, path=f"{path}.{key}")
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                self._validate_no_lookahead(item, as_of=as_of, path=f"{path}[{index}]")
            return
        if isinstance(value, str):
            try:
                candidate = parse_date(value, field_name=path)
            except ValueError:
                return
            if candidate > as_of:
                raise DatasetValidationError(f"lookahead date {value} at {path} exceeds {as_of.isoformat()}")