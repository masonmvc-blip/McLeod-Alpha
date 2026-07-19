from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from engine.datasets import DatasetBuilder, DatasetLoader, DatasetValidationError, DatasetValidator


REPO_ROOT = Path(__file__).resolve().parent.parent


def _snapshots() -> tuple[dict[str, object], ...]:
    return (
        {
            "snapshot_id": "spy-2024-01-02",
            "snapshot_date": "2024-01-02",
            "prices": {"SPY": 472.65},
            "sec_filings": [{"published_at": "2024-01-02", "form": "8-K"}],
            "earnings": [{"reported_at": "2024-01-02", "symbol": "SPY"}],
            "macro": [{"released_at": "2024-01-02", "series": "CPI"}],
            "evidence": [{"observed_at": "2024-01-02", "evidence_id": "ev-1"}],
        },
        {
            "snapshot_id": "spy-2024-01-03",
            "snapshot_date": "2024-01-03",
            "prices": {"SPY": 468.79},
            "analyst_revisions": [{"published_at": "2024-01-03", "symbol": "SPY"}],
            "evidence": [{"observed_at": "2024-01-03", "evidence_id": "ev-2"}],
        },
    )


def _build(path: Path, snapshots: tuple[dict[str, object], ...] | None = None, *, expected_dates: tuple[str, ...] | None = None) -> Path:
    return DatasetBuilder().build(
        output_dir=path,
        dataset_id="spy-us-2024-01",
        dataset_name="SPY January 2024",
        market="US Equities",
        snapshots=snapshots or _snapshots(),
        expected_dates=expected_dates,
    )


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_dataset_creation_manifest_and_loader_are_deterministic(tmp_path: Path) -> None:
    first = _build(tmp_path / "first")
    second = _build(tmp_path / "second", tuple(reversed(_snapshots())))
    assert _file_bytes(first) == _file_bytes(second)

    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    metadata = json.loads((first / "metadata.json").read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == metadata["dataset_id"] == "spy-us-2024-01"
    assert manifest["content_hash"] == metadata["content_hash"]
    assert manifest["creation_version"] == "mcleod-alpha-datasets-1"
    assert sorted(manifest["snapshot_hashes"]) == ["spy-2024-01-02", "spy-2024-01-03"]

    loader = DatasetLoader.load(first)
    assert [row["snapshot_id"] for row in loader] == ["spy-2024-01-02", "spy-2024-01-03"]
    assert loader.load_snapshot("spy-2024-01-02")["prices"]["SPY"] == 472.65
    assert loader.load_by_date("2024-01-03")["snapshot_id"] == "spy-2024-01-03"
    assert [row["snapshot_id"] for row in loader.load_range("2024-01-03", "2024-01-03")] == ["spy-2024-01-03"]


def test_immutable_rebuild_at_same_path_accepts_identical_content(tmp_path: Path) -> None:
    path = tmp_path / "immutable"
    _build(path)
    assert _build(path) == path
    with pytest.raises(FileExistsError):
        _build(path, _snapshots()[:1])


def test_missing_expected_date_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DatasetValidationError, match="missing or unexpected snapshot dates"):
        _build(tmp_path / "missing", expected_dates=("2024-01-02", "2024-01-03", "2024-01-04"))


def test_duplicate_snapshot_id_is_rejected(tmp_path: Path) -> None:
    duplicate = list(_snapshots())
    duplicate[1] = {**duplicate[1], "snapshot_id": "spy-2024-01-02"}
    with pytest.raises(DatasetValidationError, match="duplicate snapshot ID"):
        _build(tmp_path / "duplicate-id", tuple(duplicate))


def test_duplicate_snapshot_hash_is_rejected(tmp_path: Path) -> None:
    path = _build(tmp_path / "duplicate-hash")
    timeline_path = path / "timeline" / "index.json"
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    timeline[1]["snapshot_hash"] = timeline[0]["snapshot_hash"]
    timeline_path.write_text(json.dumps(timeline), encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="duplicate snapshot hash"):
        DatasetValidator().validate(path)


def test_lookahead_information_is_rejected(tmp_path: Path) -> None:
    future = list(_snapshots())
    future[0] = {
        **future[0],
        "sec_filings": [{"published_at": "2024-01-03", "form": "10-K"}],
        "future_prices": [{"date": "2024-01-03", "close": 999.0}],
        "evidence": [{"observed_at": "2024-01-03", "evidence_id": "future"}],
    }
    with pytest.raises(DatasetValidationError, match="lookahead"):
        _build(tmp_path / "lookahead", tuple(future))


def test_cli_rebuild_produces_byte_identical_dataset(tmp_path: Path) -> None:
    source = {
        "dataset_id": "spy-us-2024-01",
        "dataset_name": "SPY January 2024",
        "market": "US Equities",
        "snapshots": list(_snapshots()),
    }
    input_path = tmp_path / "raw.json"
    input_path.write_text(json.dumps(source), encoding="utf-8")
    first = tmp_path / "cli-first"
    second = tmp_path / "cli-second"
    command = [sys.executable, str(REPO_ROOT / "tools" / "build_dataset.py"), "--input", str(input_path)]
    subprocess.run([*command, "--output", str(first)], check=True, cwd=REPO_ROOT)
    subprocess.run([*command, "--output", str(second)], check=True, cwd=REPO_ROOT)
    assert _file_bytes(first) == _file_bytes(second)