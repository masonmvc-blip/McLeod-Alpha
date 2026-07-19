from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence

from .experiment import Experiment, canonical_bytes, content_hash
from .experiment_report import summary_markdown
from .factor_definition import FactorDefinition
from .factor_engine import evaluate_factors
from .metric_engine import calculate_metrics
from .statistical_tests import bootstrap_confidence_interval, effect_size, mann_whitney, stability, t_test, train_test_split


def run_experiment(experiment: Experiment, *, snapshots: Sequence[Mapping[str, Any]], factors: Sequence[FactorDefinition], output_root: Path | str) -> dict[str, Any]:
    ordered = tuple(sorted((dict(snapshot) for snapshot in snapshots), key=lambda row: (str(row["snapshot_date"]), str(row["snapshot_id"]))))
    evaluations = evaluate_factors(ordered, factors)
    signals = [sum(row["signals"].values()) / len(row["signals"]) for row in evaluations]
    returns = [float(row.get("valuation", {}).get("realized_alpha", 0.0)) for row in ordered]
    metrics = calculate_metrics(returns, signals)
    statistics = {"bootstrap_ci": bootstrap_confidence_interval(returns, seed=experiment.seed), "t_test": t_test(returns), "mann_whitney": mann_whitney(returns, [0.0] * len(returns)), "effect_size": effect_size(returns), "stability": stability(returns), "train_test": train_test_split(returns)}
    experiment_payload = {**experiment.to_dict(), "status": "PASSED"}
    files = {"experiment.json": canonical_bytes(experiment_payload), "metrics.json": canonical_bytes(metrics), "statistics.json": canonical_bytes(statistics)}
    files["summary.md"] = summary_markdown(experiment_payload, metrics, statistics).encode("utf-8")
    manifest = {"experiment_id": experiment.experiment_id, "dataset_hash": content_hash(ordered), "artifact_hashes": {name: sha256(data).hexdigest() for name, data in sorted(files.items())}}
    files["manifest.json"] = canonical_bytes(manifest)
    target = Path(output_root) / experiment.experiment_id
    if target.exists():
        existing = {path.name: path.read_bytes() for path in target.iterdir() if path.is_file()}
        if existing != files: raise FileExistsError(f"experiment artifact conflict: {target}")
    else:
        with TemporaryDirectory(prefix="research_lab_") as temporary:
            stage = Path(temporary) / experiment.experiment_id; stage.mkdir()
            for name, data in files.items(): (stage / name).write_bytes(data)
            target.parent.mkdir(parents=True, exist_ok=True); pending = target.parent / f".{target.name}.staging"
            if pending.exists(): shutil.rmtree(pending)
            shutil.copytree(stage, pending); os.replace(pending, target)
    return {"experiment": experiment_payload, "metrics": metrics, "statistics": statistics, "output_path": str(target), "manifest": manifest}