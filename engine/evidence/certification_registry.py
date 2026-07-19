from __future__ import annotations

import json
from pathlib import Path

from .certification_schema import Certification, canonical_bytes


class CertificationRegistry:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def register(self, certification: Certification) -> None:
        entries = self._read()
        existing = entries.get(certification.certification_id)
        payload = certification.to_dict()
        if existing is not None and canonical_bytes(existing) != canonical_bytes(payload):
            raise ValueError("immutable certification conflict")
        if existing is None:
            entries[certification.certification_id] = payload
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(canonical_bytes(entries))

    def _read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}