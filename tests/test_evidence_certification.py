from __future__ import annotations

from pathlib import Path
import pytest

from engine.evidence import CertificationPolicy, certify_experiment
from engine.evidence.certification_registry import CertificationRegistry
from engine.evidence.reproducibility_check import load_verified_artifacts
from engine.research_lab import Experiment, FactorDefinition, run_experiment


def _policy() -> CertificationPolicy:
    return CertificationPolicy("evidence", "1.0.0", "2024-01-04T00:00:00Z", "test", 0.0, 0.0, -1.0, 0.0, 1.0, 1.0, -1.0, 1.0, -1.0)


def _experiment(root: Path) -> Path:
    experiment = Experiment.create(name="evidence", description="test", hypothesis="positive", factors=("signal",), dataset="immutable", replay_window=("2024-01-01", "2024-01-03"), benchmark="cash", metrics=("CAGR",), seed=7)
    snapshots = ({"snapshot_id": "1", "snapshot_date": "2024-01-01", "signal": 1, "valuation": {"realized_alpha": .01}}, {"snapshot_id": "2", "snapshot_date": "2024-01-02", "signal": 1, "valuation": {"realized_alpha": .02}}, {"snapshot_id": "3", "snapshot_date": "2024-01-03", "signal": 1, "valuation": {"realized_alpha": .01}})
    return Path(run_experiment(experiment, snapshots=snapshots, factors=(FactorDefinition("signal", lambda row: row["signal"]),), output_root=root)["output_path"])


def test_deterministic_certification_artifacts_and_registry(tmp_path: Path) -> None:
    experiment = _experiment(tmp_path / "research")
    first = certify_experiment(experiment, _policy(), tmp_path / "evidence")
    second = certify_experiment(experiment, _policy(), tmp_path / "evidence_repeat")
    assert first["certification"].certification_id == second["certification"].certification_id
    assert first["certification"].decision == second["certification"].decision
    first_files = {path.name: path.read_bytes() for path in Path(first["output_path"]).iterdir()}
    second_files = {path.name: path.read_bytes() for path in Path(second["output_path"]).iterdir()}
    assert first_files == second_files
    registry = CertificationRegistry(tmp_path / "registry.json")
    registry.register(first["certification"]); registry.register(second["certification"])
    assert (tmp_path / "evidence" / first["certification"].certification_id / "manifest.json").is_file()


def test_policy_version_and_fail_closed_artifact_integrity(tmp_path: Path) -> None:
    experiment = _experiment(tmp_path / "research")
    assert _policy().policy_hash != CertificationPolicy("evidence", "1.0.1", "2024-01-04T00:00:00Z", "test", 0.0, 0.0, -1.0, 0.0, 1.0, 1.0, -1.0, 1.0, -1.0).policy_hash
    (experiment / "metrics.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        load_verified_artifacts(experiment)
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        certify_experiment(experiment, _policy(), tmp_path / "evidence")