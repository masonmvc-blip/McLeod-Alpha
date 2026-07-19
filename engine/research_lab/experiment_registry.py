from __future__ import annotations

import json
from pathlib import Path

from .experiment import Experiment, canonical_bytes


STATUSES = frozenset(("PROPOSED", "RUNNING", "PASSED", "FAILED", "REJECTED"))


class ExperimentRegistry:
    def __init__(self, path: Path): self.path = Path(path)
    def register(self, experiment: Experiment) -> None:
        entries = self._read(); entries[experiment.experiment_id] = experiment.to_dict(); self._write(entries)
    def update_status(self, experiment_id: str, status: str) -> None:
        if status not in STATUSES: raise ValueError("invalid experiment status")
        entries = self._read(); entries[experiment_id]["status"] = status; self._write(entries)
    def _read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
    def _write(self, entries: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True); self.path.write_bytes(canonical_bytes(entries))