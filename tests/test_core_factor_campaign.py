from __future__ import annotations

from pathlib import Path

from tools.run_core_factor_campaign import build_campaign


def test_campaign_fails_closed_and_generates_byte_identical_artifacts(tmp_path: Path) -> None:
    (tmp_path / "artifacts/replay/example_dataset/snapshots").mkdir(parents=True)
    first = build_campaign(repository_root=tmp_path, output_root=tmp_path / "first")
    second = build_campaign(repository_root=tmp_path, output_root=tmp_path / "second")
    assert first["summary"]["experiments_completed"] == 0
    assert len(first["summary"]["not_ready_factors"]) == 10
    assert {path.name: path.read_bytes() for path in (tmp_path / "first").iterdir()} == {path.name: path.read_bytes() for path in (tmp_path / "second").iterdir()}