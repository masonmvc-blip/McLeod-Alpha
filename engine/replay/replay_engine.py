from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .replay_report import write_replay_report
from .replay_runner import ReplayRunResult, ReplayStageAdapter, run_historical_replay
from .snapshot_loader import load_historical_snapshots


SCHEMA_VERSION = "1.0.0"


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", dir=str(path.parent), delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


@dataclass(frozen=True)
class HistoricalReplayResult:
    replay: ReplayRunResult
    report_path: str
    manifest_path: str


def run_replay_engine(
    *,
    snapshot_root: Path,
    output_root: Path,
    write_artifacts: bool,
    adapter: ReplayStageAdapter | None = None,
) -> HistoricalReplayResult:
    snapshots = load_historical_snapshots(snapshot_root)
    replay_root = Path(output_root)

    replay_result = run_historical_replay(
        snapshots=snapshots,
        output_root=replay_root,
        write_artifacts=write_artifacts,
        adapter=adapter,
    )

    report_path = replay_root / "replay_report.md"
    manifest_path = replay_root / "replay_manifest.json"

    if write_artifacts:
        write_replay_report(replay_result, report_path=report_path)

        manifest_payload = {
            "schema_version": SCHEMA_VERSION,
            "replay_id": replay_result.replay_id,
            "snapshot_count": replay_result.snapshot_count,
            "replay_content_hash": replay_result.content_hash,
            "artifact_hashes": {},
        }

        artifact_hashes: dict[str, str] = {}
        for artifact_path in replay_result.artifact_paths + (str(report_path),):
            path = Path(artifact_path)
            artifact_hashes[path.name] = _sha_bytes(path.read_bytes())

        manifest_payload["artifact_hashes"] = dict(sorted(artifact_hashes.items(), key=lambda item: item[0]))
        manifest_bytes = (json.dumps(manifest_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        _atomic_write(manifest_path, manifest_bytes)

    return HistoricalReplayResult(
        replay=replay_result,
        report_path=str(report_path),
        manifest_path=str(manifest_path),
    )
