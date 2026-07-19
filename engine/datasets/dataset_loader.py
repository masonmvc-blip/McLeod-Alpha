"""Deterministic read-only access to immutable replay datasets."""

from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Iterator

from .dataset_validator import DatasetValidator


class DatasetLoader:
    def __init__(self, dataset_dir: Path | str) -> None:
        self.dataset_dir = Path(dataset_dir)
        DatasetValidator().validate(self.dataset_dir)
        self.metadata = self._read_json("metadata.json")
        self.manifest = self._read_json("manifest.json")
        self._timeline = tuple(self._read_json("timeline/index.json"))
        self._by_id = {row["snapshot_id"]: row for row in self._timeline}
        self._by_date = {row["snapshot_date"]: row for row in self._timeline}

    @classmethod
    def load(cls, dataset_dir: Path | str) -> "DatasetLoader":
        return cls(dataset_dir)

    def load_range(self, start_date: str, end_date: str) -> Iterator[dict[str, Any]]:
        for row in self._timeline:
            if start_date <= row["snapshot_date"] <= end_date:
                yield self.load_snapshot(row["snapshot_id"])

    def load_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        row = self._by_id.get(snapshot_id)
        if row is None:
            raise KeyError(f"Unknown snapshot ID: {snapshot_id}")
        return self._read_json(row["snapshot_path"])

    def load_by_date(self, snapshot_date: str) -> dict[str, Any]:
        row = self._by_date.get(snapshot_date)
        if row is None:
            raise KeyError(f"Unknown snapshot date: {snapshot_date}")
        return self.load_snapshot(row["snapshot_id"])

    def __iter__(self) -> Iterator[dict[str, Any]]:
        for row in self._timeline:
            yield self.load_snapshot(row["snapshot_id"])

    def _read_json(self, relative_path: str) -> Any:
        return json.loads((self.dataset_dir / relative_path).read_text(encoding="utf-8"))