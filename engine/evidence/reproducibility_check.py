from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .certification_schema import canonical_bytes, content_hash


REQUIRED_ARTIFACTS = frozenset(("experiment.json", "metrics.json", "statistics.json", "summary.md", "manifest.json"))


def load_verified_artifacts(path: Path | str) -> dict[str, Any]:
    root = Path(path)
    if not root.is_dir() or not REQUIRED_ARTIFACTS.issubset({entry.name for entry in root.iterdir() if entry.is_file()}):
        raise ValueError("incomplete experiment artifacts")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    hashes = manifest.get("artifact_hashes")
    if not isinstance(hashes, dict) or set(hashes) != REQUIRED_ARTIFACTS - {"manifest.json"}:
        raise ValueError("invalid experiment manifest")
    for name, expected in hashes.items():
        if sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"artifact hash mismatch: {name}")
    experiment = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
    experiment_id = experiment.get("experiment_id")
    if not isinstance(experiment_id, str) or experiment_id != manifest.get("experiment_id") or root.name != experiment_id:
        raise ValueError("experiment identity mismatch")
    payload = {
        "experiment": experiment,
        "metrics": json.loads((root / "metrics.json").read_text(encoding="utf-8")),
        "statistics": json.loads((root / "statistics.json").read_text(encoding="utf-8")),
        "manifest": manifest,
    }
    payload["artifact_hash"] = content_hash(payload)
    return payload