from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .evidence_record import (
    EvidenceConflictError,
    EvidenceLineageRecord,
    EvidenceRecord,
)


DEFAULT_LEDGER_ROOT = Path("artifacts") / "cio" / "evidence_ledger"


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _line(record: dict[str, Any]) -> str:
    return _stable_json(record)


def _sha256_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", dir=str(path.parent), delete=False) as handle:
        handle.write(content)
        tmp = Path(handle.name)
    os.replace(tmp, path)


def _atomic_write_text(path: Path, content: str) -> None:
    _atomic_write_bytes(path, content.encode("utf-8"))


def _append_line_atomic(path: Path, line: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    content = existing + line + "\n"
    _atomic_write_text(path, content)


def _jsonl_load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for text in path.read_text(encoding="utf-8").splitlines():
        stripped = text.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


@dataclass(frozen=True)
class EvidenceLedgerIntegrity:
    ok: bool
    missing_files: tuple[str, ...]
    hash_mismatches: tuple[str, ...]
    details: dict[str, Any]


class EvidenceLedger:
    def __init__(self, root_path: Path = DEFAULT_LEDGER_ROOT) -> None:
        self.root_path = Path(root_path)
        self.root_path.mkdir(parents=True, exist_ok=True)
        self.evidence_path = self.root_path / "evidence.jsonl"
        self.lineage_path = self.root_path / "lineage.jsonl"
        self.index_path = self.root_path / "index.json"
        self.manifest_path = self.root_path / "ledger_manifest.json"
        self._ensure_base_files()

    def _ensure_base_files(self) -> None:
        if not self.evidence_path.exists():
            _atomic_write_text(self.evidence_path, "")
        if not self.lineage_path.exists():
            _atomic_write_text(self.lineage_path, "")
        if not self.index_path.exists() or not self.manifest_path.exists():
            self.rebuild_index()

    def append_evidence(self, record: EvidenceRecord) -> EvidenceRecord:
        existing = {item.evidence_id: item for item in self._load_evidence_records()}
        prior = existing.get(record.evidence_id)
        if prior is not None:
            if prior.to_dict() == record.to_dict():
                return prior
            raise EvidenceConflictError(f"Conflicting evidence_id: {record.evidence_id}")

        _append_line_atomic(self.evidence_path, _line(record.to_dict()))
        self.rebuild_index()
        return record

    def append_many(self, records: tuple[EvidenceRecord, ...]) -> tuple[EvidenceRecord, ...]:
        written: list[EvidenceRecord] = []
        for record in records:
            written.append(self.append_evidence(record))
        return tuple(written)

    def link(self, lineage_record: EvidenceLineageRecord) -> EvidenceLineageRecord:
        evidence_ids = {item.evidence_id for item in self._load_evidence_records()}
        if lineage_record.evidence_id not in evidence_ids:
            raise EvidenceConflictError(f"Unknown evidence_id for lineage: {lineage_record.evidence_id}")

        existing = {item.lineage_id: item for item in self._load_lineage_records()}
        prior = existing.get(lineage_record.lineage_id)
        if prior is not None:
            if prior.to_dict() == lineage_record.to_dict():
                return prior
            raise EvidenceConflictError(f"Conflicting lineage_id: {lineage_record.lineage_id}")

        _append_line_atomic(self.lineage_path, _line(lineage_record.to_dict()))
        self.rebuild_index()
        return lineage_record

    def link_many(self, lineage_records: tuple[EvidenceLineageRecord, ...]) -> tuple[EvidenceLineageRecord, ...]:
        written: list[EvidenceLineageRecord] = []
        for record in lineage_records:
            written.append(self.link(record))
        return tuple(written)

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        for record in self._load_evidence_records():
            if record.evidence_id == evidence_id:
                return record
        return None

    def get_lineage_for_evidence(self, evidence_id: str) -> tuple[EvidenceLineageRecord, ...]:
        items = [item for item in self._load_lineage_records() if item.evidence_id == evidence_id]
        return tuple(sorted(items, key=lambda item: (item.created_at, item.target_type, item.target_id, item.lineage_id)))

    def get_lineage_for_target(self, target_type: str, target_id: str) -> tuple[EvidenceLineageRecord, ...]:
        items = [
            item
            for item in self._load_lineage_records()
            if item.target_type == str(target_type) and item.target_id == str(target_id)
        ]
        return tuple(sorted(items, key=lambda item: (item.created_at, item.evidence_id, item.lineage_id)))

    def rebuild_index(self) -> dict[str, Any]:
        evidence = self._load_evidence_records()
        lineage = self._load_lineage_records()

        evidence_ids = sorted(item.evidence_id for item in evidence)
        by_symbol: dict[str, int] = {}
        by_target: dict[str, int] = {}
        superseded_pairs: list[tuple[str, str]] = []

        for item in evidence:
            by_symbol[item.symbol] = by_symbol.get(item.symbol, 0) + 1
            if item.supersedes_evidence_id:
                superseded_pairs.append((item.supersedes_evidence_id, item.evidence_id))

        for item in lineage:
            key = f"{item.target_type}:{item.target_id}"
            by_target[key] = by_target.get(key, 0) + 1

        index_payload = {
            "total_evidence": len(evidence),
            "total_lineage": len(lineage),
            "evidence_ids": evidence_ids,
            "evidence_by_symbol": dict(sorted(by_symbol.items(), key=lambda item: item[0])),
            "lineage_by_target": dict(sorted(by_target.items(), key=lambda item: item[0])),
            "superseded_pairs": [list(pair) for pair in sorted(superseded_pairs)],
            "content_hash": sha256(
                _stable_json(
                    {
                        "evidence": [item.to_dict() for item in evidence],
                        "lineage": [item.to_dict() for item in lineage],
                    }
                ).encode("utf-8")
            ).hexdigest(),
        }

        _atomic_write_text(self.index_path, json.dumps(index_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

        manifest = self._build_manifest()
        _atomic_write_text(self.manifest_path, json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        return index_payload

    def verify_integrity(self) -> EvidenceLedgerIntegrity:
        missing: list[str] = []
        mismatches: list[str] = []

        for path in (self.evidence_path, self.lineage_path, self.index_path, self.manifest_path):
            if not path.exists():
                missing.append(path.name)

        if missing:
            return EvidenceLedgerIntegrity(
                ok=False,
                missing_files=tuple(sorted(missing)),
                hash_mismatches=(),
                details={"reason": "missing ledger files"},
            )

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        expected_hashes = manifest.get("file_hashes", {})

        observed_hashes = {
            "evidence.jsonl": _sha256_bytes(self.evidence_path.read_bytes()),
            "lineage.jsonl": _sha256_bytes(self.lineage_path.read_bytes()),
            "index.json": _sha256_bytes(self.index_path.read_bytes()),
        }

        for name, observed in sorted(observed_hashes.items(), key=lambda item: item[0]):
            expected = str(expected_hashes.get(name, ""))
            if observed != expected:
                mismatches.append(name)

        return EvidenceLedgerIntegrity(
            ok=not mismatches,
            missing_files=(),
            hash_mismatches=tuple(sorted(mismatches)),
            details={
                "observed_hashes": observed_hashes,
                "expected_hashes": expected_hashes,
                "manifest_content_hash": manifest.get("manifest_content_hash", ""),
            },
        )

    def export_chain(self, target_type: str, target_id: str) -> dict[str, Any]:
        from .evidence_replay import EvidenceReplay

        return EvidenceReplay(self).reconstruct_chain(target_type=target_type, target_id=target_id)

    def _load_evidence_records(self) -> tuple[EvidenceRecord, ...]:
        rows = _jsonl_load(self.evidence_path)
        items = tuple(EvidenceRecord.from_dict(row) for row in rows)
        return tuple(sorted(items, key=lambda item: (item.observed_at, item.evidence_id)))

    def _load_lineage_records(self) -> tuple[EvidenceLineageRecord, ...]:
        rows = _jsonl_load(self.lineage_path)
        items = tuple(EvidenceLineageRecord.from_dict(row) for row in rows)
        return tuple(sorted(items, key=lambda item: (item.created_at, item.lineage_id)))

    def _build_manifest(self) -> dict[str, Any]:
        file_hashes = {
            "evidence.jsonl": _sha256_bytes(self.evidence_path.read_bytes()) if self.evidence_path.exists() else _sha256_bytes(b""),
            "lineage.jsonl": _sha256_bytes(self.lineage_path.read_bytes()) if self.lineage_path.exists() else _sha256_bytes(b""),
            "index.json": _sha256_bytes(self.index_path.read_bytes()) if self.index_path.exists() else _sha256_bytes(b""),
        }
        manifest_core = {
            "ledger_root": str(self.root_path),
            "files": ["evidence.jsonl", "lineage.jsonl", "index.json", "ledger_manifest.json"],
            "file_hashes": dict(sorted(file_hashes.items(), key=lambda item: item[0])),
            "schema_version": "1.0.0",
        }
        manifest_core["manifest_content_hash"] = sha256(_stable_json(manifest_core).encode("utf-8")).hexdigest()
        return manifest_core
