"""Local JSON/JSONL historical source contract; no network, credentials, or vendor calls.

Each source directory contains ``*.json`` (an array or ``{"records": [...]}``)
or JSONL files. Records need the connector's documented availability date.
Future availability records are excluded; malformed dates or future nested dates
within eligible records fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from engine.datasets.dataset_schema import canonical_json_bytes, hash_bytes, normalize_json, parse_date


SOURCE_SCHEMA_VERSION = "1.0.0"


class SourceValidationError(ValueError):
    """A local raw source is malformed or contains a lookahead violation."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): thaw(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class SourceFragment:
    source_name: str
    as_of_date: str
    symbols: tuple[str, ...]
    records: tuple[Mapping[str, Any], ...]
    source_hash: str
    schema_version: str

    def to_dict(self) -> dict[str, Any]:
        return {"source_name": self.source_name, "as_of_date": self.as_of_date, "symbols": list(self.symbols), "records": [thaw(record) for record in self.records], "source_hash": self.source_hash, "schema_version": self.schema_version}


class HistoricalSourceConnector(Protocol):
    source_name: str
    schema_version: str

    def fetch(self, as_of_date: str, symbols: Sequence[str], source_root: Path | str) -> SourceFragment:
        """Return an immutable deterministic fragment known on the requested date."""


class FileBackedConnector:
    source_name = "base"
    source_directory = ""
    availability_date_field = "date"
    schema_version = SOURCE_SCHEMA_VERSION

    def fetch(self, as_of_date: str, symbols: Sequence[str], source_root: Path | str) -> SourceFragment:
        as_of = parse_date(as_of_date, field_name="as_of_date")
        canonical_symbols = tuple(sorted({str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()}))
        if not canonical_symbols:
            raise SourceValidationError("symbols must contain at least one non-empty symbol")
        directory = Path(source_root) / self.source_directory
        if directory.exists() and not directory.is_dir():
            raise SourceValidationError(f"source path is not a directory: {directory}")
        records: list[dict[str, Any]] = []
        paths = (sorted(directory.glob("*.json")) + sorted(directory.glob("*.jsonl"))) if directory.exists() else []
        for path in paths:
            for record in self._load_records(path):
                normalized = normalize_json(record)
                available_on = self._availability_date(normalized, path)
                if available_on > as_of:
                    continue
                self._validate_no_lookahead(normalized, as_of=as_of, path=path.name)
                symbol = str(normalized.get("symbol") or "").upper().strip()
                if symbol and symbol not in canonical_symbols:
                    continue
                records.append(normalized)
        records.sort(key=lambda record: (str(record.get(self.availability_date_field)), str(record.get("symbol") or ""), hash_bytes(canonical_json_bytes(record))))
        frozen_records = tuple(_freeze(record) for record in records)
        payload = {"source_name": self.source_name, "as_of_date": as_of.isoformat(), "symbols": list(canonical_symbols), "records": [thaw(record) for record in frozen_records], "schema_version": self.schema_version}
        return SourceFragment(self.source_name, as_of.isoformat(), canonical_symbols, frozen_records, hash_bytes(canonical_json_bytes(payload)), self.schema_version)

    def _availability_date(self, record: Mapping[str, Any], path: Path):
        if self.availability_date_field not in record:
            raise SourceValidationError(f"missing {self.availability_date_field} in {path.name}")
        try:
            return parse_date(record[self.availability_date_field], field_name=self.availability_date_field)
        except ValueError as exc:
            raise SourceValidationError(f"malformed {self.availability_date_field} in {path.name}") from exc

    @staticmethod
    def _load_records(path: Path) -> list[dict[str, Any]]:
        try:
            if path.suffix == ".jsonl":
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            else:
                raw = json.loads(path.read_text(encoding="utf-8"))
                rows = raw.get("records") if isinstance(raw, dict) else raw
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise SourceValidationError(f"source file must contain an array of objects: {path}")
            return rows
        except json.JSONDecodeError as exc:
            raise SourceValidationError(f"invalid JSON source: {path}") from exc

    def _validate_no_lookahead(self, value: Any, *, as_of: Any, path: str) -> None:
        if isinstance(value, Mapping):
            lowered = {str(key).lower(): key for key in value}
            for marker in ("future", "is_future", "lookahead"):
                if marker in lowered and bool(value[lowered[marker]]):
                    raise SourceValidationError(f"lookahead marker at {path}.{lowered[marker]}")
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
                raise SourceValidationError(f"future date {value} at {path} exceeds {as_of.isoformat()}")