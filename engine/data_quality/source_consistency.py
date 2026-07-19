"""Read raw JSON/JSONL sources and verify deterministic record/source hashes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.datasets.dataset_schema import canonical_json_bytes, hash_bytes, normalize_json

from .coverage_schema import AuditInputError


def load_source_records(source_root: Path, source: str) -> tuple[list[dict[str, Any]], str, tuple[str, ...]]:
    directory = source_root / source
    if not directory.exists():
        return [], hash_bytes(b""), ()
    if not directory.is_dir():
        raise AuditInputError(f"source path is not a directory: {directory}")
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    content = bytearray()
    for path in sorted((*directory.glob("*.json"), *directory.glob("*.jsonl"))):
        raw = path.read_bytes()
        content.extend(path.name.encode("utf-8") + b"\0" + raw)
        try:
            values = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()] if path.suffix == ".jsonl" else json.loads(raw.decode("utf-8"))
            values = values.get("records") if isinstance(values, dict) else values
            if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
                raise ValueError("must contain a list of objects")
            for ordinal, value in enumerate(values, 1):
                clean = normalize_json(value)
                expected = clean.pop("record_hash", None)
                actual = hash_bytes(canonical_json_bytes(clean))
                if expected is not None and expected != actual:
                    errors.append(f"{source}/{path.name}:{ordinal}: record_hash mismatch")
                records.append(clean)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{source}/{path.name}: invalid source content ({exc})")
    return records, hash_bytes(bytes(content)), tuple(sorted(errors))


def source_root_hash(source_root: Path) -> str:
    if not source_root.is_dir():
        raise AuditInputError(f"source root is not a directory: {source_root}")
    payload = bytearray()
    for path in sorted(item for item in source_root.rglob("*") if item.is_file()):
        payload.extend(str(path.relative_to(source_root)).encode("utf-8") + b"\0" + path.read_bytes())
    return hash_bytes(bytes(payload))