"""Strict offline import contract for raw historical sources.

Input layout uses directories named ``sec``, ``prices``, ``fundamentals``,
``macro``, ``analysts``, ``news``, or ``universes`` containing CSV, JSON, or
JSONL records. Every record requires its source-specific availability field and
``source_metadata`` object. Symbol is required except for macro records.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Any, Iterable, Mapping

from engine.datasets.dataset_schema import canonical_json_bytes, hash_bytes, normalize_json, parse_date


IMPORT_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class SourceImportSummary:
    source_name: str
    imported_records: int
    rejected_records: int
    duplicate_records: tuple[str, ...]
    malformed_records: tuple[str, ...]
    missing_required_fields: tuple[str, ...]
    output_hash: str = ""


@dataclass(frozen=True)
class ImportReport:
    schema_version: str
    imported_records: int
    rejected_records: int
    duplicate_records: tuple[str, ...]
    malformed_records: tuple[str, ...]
    missing_required_fields: tuple[str, ...]
    sources: tuple[SourceImportSummary, ...]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "sources": [asdict(source) for source in self.sources]}


class ImportValidationError(ValueError):
    def __init__(self, message: str, report: ImportReport) -> None:
        super().__init__(message)
        self.report = report


class HistoricalSourceImporter:
    """Base importer: normalize local external records into immutable raw-source JSONL."""

    source_name = "base"
    availability_date_field = "date"
    requires_symbol = True

    def collect(self, input_root: Path | str) -> tuple[list[dict[str, Any]], SourceImportSummary]:
        root = Path(input_root) / self.source_name
        raw_records: list[tuple[Path, int, dict[str, Any]]] = []
        malformed: list[str] = []
        missing: list[str] = []
        if root.exists() and not root.is_dir():
            malformed.append(f"{root}: source path is not a directory")
        elif root.exists():
            for path in sorted(root.glob("*.csv")) + sorted(root.glob("*.json")) + sorted(root.glob("*.jsonl")):
                try:
                    raw_records.extend(self._read_file(path))
                except ValueError as exc:
                    malformed.append(str(exc))
        normalized: list[dict[str, Any]] = []
        duplicates: list[str] = []
        hashes: set[str] = set()
        for path, ordinal, record in raw_records:
            label = f"{path.name}:{ordinal}"
            try:
                clean = self._normalize_record(record, label)
            except KeyError as exc:
                missing.append(f"{label}: {exc.args[0]}")
                continue
            except ValueError as exc:
                malformed.append(f"{label}: {exc}")
                continue
            record_hash = hash_bytes(canonical_json_bytes(clean))
            if record_hash in hashes:
                duplicates.append(f"{label}: {record_hash}")
                continue
            hashes.add(record_hash)
            clean["record_hash"] = record_hash
            normalized.append(clean)
        normalized.sort(key=lambda row: (str(row[self.availability_date_field]), str(row.get("symbol", "")), str(row["record_hash"])))
        summary = SourceImportSummary(
            source_name=self.source_name,
            imported_records=len(normalized),
            rejected_records=len(malformed) + len(missing) + len(duplicates),
            duplicate_records=tuple(sorted(duplicates)),
            malformed_records=tuple(sorted(malformed)),
            missing_required_fields=tuple(sorted(missing)),
        )
        return normalized, summary

    def _normalize_record(self, record: Mapping[str, Any], label: str) -> dict[str, Any]:
        try:
            clean = normalize_json(dict(record))
        except Exception as exc:
            raise ValueError(f"unsupported record value: {exc}") from exc
        required = [self.availability_date_field, "source_metadata"]
        if self.requires_symbol:
            required.append("symbol")
        for field in required:
            if field not in clean or clean[field] in (None, ""):
                raise KeyError(f"missing required field {field}")
        try:
            clean[self.availability_date_field] = parse_date(clean[self.availability_date_field], field_name=self.availability_date_field).isoformat()
        except ValueError as exc:
            raise ValueError(f"malformed {self.availability_date_field}") from exc
        if not isinstance(clean["source_metadata"], Mapping):
            raise ValueError("source_metadata must be an object")
        if self.requires_symbol:
            symbol = str(clean["symbol"]).upper().strip()
            if not symbol:
                raise ValueError("symbol must be non-empty")
            clean["symbol"] = symbol
        return clean

    @staticmethod
    def _read_file(path: Path) -> list[tuple[Path, int, dict[str, Any]]]:
        try:
            if path.suffix == ".csv":
                with path.open(newline="", encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
            elif path.suffix == ".jsonl":
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            else:
                raw = json.loads(path.read_text(encoding="utf-8"))
                rows = raw.get("records") if isinstance(raw, dict) else raw
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise ValueError(f"{path}: expected an array of objects")
            normalized_rows: list[tuple[Path, int, dict[str, Any]]] = []
            for ordinal, row in enumerate(rows, start=1):
                if path.suffix == ".csv" and "source_metadata" in row and isinstance(row["source_metadata"], str):
                    try:
                        row["source_metadata"] = json.loads(row["source_metadata"])
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"{path}:{ordinal}: source_metadata must contain JSON object") from exc
                normalized_rows.append((path, ordinal, row))
            return normalized_rows
        except (OSError, json.JSONDecodeError, csv.Error) as exc:
            raise ValueError(f"{path}: invalid {path.suffix[1:].upper()} input") from exc


def import_all(*, input_root: Path | str, output_root: Path | str, importers: Iterable[HistoricalSourceImporter]) -> ImportReport:
    importer_list = tuple(importers)
    results = [(importer, *importer.collect(input_root)) for importer in importer_list]
    summaries = tuple(item[2] for item in results)
    report = ImportReport(
        schema_version=IMPORT_SCHEMA_VERSION,
        imported_records=sum(summary.imported_records for summary in summaries),
        rejected_records=sum(summary.rejected_records for summary in summaries),
        duplicate_records=tuple(sorted(item for summary in summaries for item in summary.duplicate_records)),
        malformed_records=tuple(sorted(item for summary in summaries for item in summary.malformed_records)),
        missing_required_fields=tuple(sorted(item for summary in summaries for item in summary.missing_required_fields)),
        sources=summaries,
    )
    if report.rejected_records:
        raise ImportValidationError("historical import rejected invalid records", report)
    target = Path(output_root)
    with TemporaryDirectory(prefix="mcleod_import_") as temporary_root:
        staging = Path(temporary_root) / "raw_sources"
        output_summaries: list[SourceImportSummary] = []
        for importer, records, summary in results:
            destination = staging / importer.source_name / "records.jsonl"
            destination.parent.mkdir(parents=True)
            content = "".join(
                json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                for record in records
            ).encode("utf-8")
            destination.write_bytes(content)
            output_summaries.append(SourceImportSummary(**{**asdict(summary), "output_hash": hash_bytes(content)}))
        final_report = ImportReport(**{**asdict(report), "sources": tuple(output_summaries)})
        manifest = {
            "schema_version": IMPORT_SCHEMA_VERSION,
            "source_hashes": {summary.source_name: summary.output_hash for summary in output_summaries},
            "content_hash": hash_bytes(canonical_json_bytes({"report": final_report.to_dict(), "source_hashes": {summary.source_name: summary.output_hash for summary in output_summaries}})),
        }
        (staging / "import_report.json").write_bytes(canonical_json_bytes(final_report.to_dict()))
        (staging / "import_manifest.json").write_bytes(canonical_json_bytes(manifest))
        if target.exists():
            existing = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
            candidate = {path.relative_to(staging): path.read_bytes() for path in staging.rglob("*") if path.is_file()}
            if existing != candidate:
                raise FileExistsError(f"raw source output already exists with different content: {target}")
            return final_report
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_target = target.parent / f".{target.name}.staging"
        if temporary_target.exists():
            shutil.rmtree(temporary_target)
        shutil.copytree(staging, temporary_target)
        os.replace(temporary_target, target)
    return final_report