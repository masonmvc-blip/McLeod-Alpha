from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.evidence import CertificationPolicy, certify_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Certify completed research-lab artifacts without rerunning experiments.")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output-root", default="artifacts/evidence")
    args = parser.parse_args()
    policy = CertificationPolicy(**json.loads(Path(args.policy).read_text(encoding="utf-8")))
    result = certify_experiment(args.experiment, policy, args.output_root)
    print(f"certification_id={result['certification'].certification_id}")
    print(f"decision={result['certification'].decision}")


if __name__ == "__main__":
    main()