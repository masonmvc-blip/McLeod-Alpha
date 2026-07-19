from __future__ import annotations

from pathlib import Path

from engine.research_lab import Experiment, FactorDefinition, run_experiment
from engine.research_lab.experiment_registry import ExperimentRegistry
from engine.research_lab.statistical_tests import bootstrap_confidence_interval, t_test


def _experiment() -> Experiment:
    return Experiment.create(name="signal", description="test", hypothesis="positive", factors=("signal",), dataset="immutable", replay_window=("2024-01-01", "2024-01-03"), benchmark="cash", metrics=("CAGR",), seed=7)


def _snapshots():
    return ({"snapshot_id": "2", "snapshot_date": "2024-01-02", "signal": 1, "valuation": {"realized_alpha": .02}}, {"snapshot_id": "1", "snapshot_date": "2024-01-01", "signal": -1, "valuation": {"realized_alpha": -.01}}, {"snapshot_id": "3", "snapshot_date": "2024-01-03", "signal": 1, "valuation": {"realized_alpha": .01}})


def test_deterministic_experiment_artifacts_and_factor_isolation(tmp_path: Path) -> None:
    factor = FactorDefinition("signal", lambda snapshot: snapshot["signal"])
    first = run_experiment(_experiment(), snapshots=_snapshots(), factors=(factor,), output_root=tmp_path)
    second = run_experiment(_experiment(), snapshots=tuple(reversed(_snapshots())), factors=(factor,), output_root=tmp_path)
    assert first["metrics"] == second["metrics"] and first["manifest"] == second["manifest"]
    assert (Path(first["output_path"]) / "manifest.json").is_file()


def test_statistics_registry_and_repeatable_ids(tmp_path: Path) -> None:
    assert _experiment().experiment_id == _experiment().experiment_id
    assert bootstrap_confidence_interval((.01, .02, -.01), seed=1) == bootstrap_confidence_interval((.01, .02, -.01), seed=1)
    assert "p_value" in t_test((.01, .02, -.01))
    registry = ExperimentRegistry(tmp_path / "registry.json"); registry.register(_experiment()); registry.update_status(_experiment().experiment_id, "PASSED")
    assert "PASSED" in (tmp_path / "registry.json").read_text(encoding="utf-8")