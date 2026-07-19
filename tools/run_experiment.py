from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.research_lab import Experiment, FactorDefinition, run_experiment


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--experiment", required=True); parser.add_argument("--snapshots", required=True); parser.add_argument("--output-root", default="artifacts/research_lab")
    args = parser.parse_args(argv)
    definition = json.loads(Path(args.experiment).read_text(encoding="utf-8")); snapshots = json.loads(Path(args.snapshots).read_text(encoding="utf-8"))
    fields = definition.pop("factor_fields"); experiment = Experiment.create(**definition)
    factors = tuple(FactorDefinition(name=field, evaluator=lambda snapshot, field=field: float(snapshot.get(field, snapshot.get("valuation", {}).get(field, 0.0)))) for field in fields)
    result = run_experiment(experiment, snapshots=snapshots, factors=factors, output_root=args.output_root)
    print(f"experiment_id={experiment.experiment_id}\noutput_path={result['output_path']}")
    return 0


if __name__ == "__main__": raise SystemExit(main())