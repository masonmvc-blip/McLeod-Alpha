"""Canonical schema and serialization primitives for replay datasets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from typing import Any, Mapping


SCHEMA_VERSION = "1.0.0"
CREATION_VERSION = "mcleod-alpha-datasets-1"


class DatasetSchemaError(ValueError):
    """Raised when a dataset payload does not meet the base schema."""


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize JSON consistently across platforms and invocations."""
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": ")) + "\n").encode("utf-8")


def hash_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def hash_payload(payload: Any) -> str:
    return hash_bytes(canonical_json_bytes(payload))


def parse_date(value: object, *, field_name: str) -> date:
    text = str(value or "").strip()
    try:
        if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
            return date.fromisoformat(text[:10])
    except ValueError:
        pass
    raise DatasetSchemaError(f"{field_name} must be an ISO-8601 date or datetime")


def normalize_json(value: Any) -> Any:
    """Convert common Python values into deterministic JSON-compatible values."""
    if isinstance(value, Mapping):
        return {str(key): normalize_json(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [normalize_json(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise DatasetSchemaError(f"Unsupported JSON value type: {type(value).__name__}")


@dataclass(frozen=True)
class DatasetMetadata:
    dataset_id: str
    dataset_name: str
    market: str
    start_date: str
    end_date: str
    snapshot_count: int
    schema_version: str
    content_hash: str
    expected_dates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    content_hash: str
    snapshot_hashes: Mapping[str, str]
    creation_version: str
    schema_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "content_hash": self.content_hash,
            "snapshot_hashes": dict(sorted(self.snapshot_hashes.items())),
            "creation_version": self.creation_version,
            "schema_version": self.schema_version,
        }