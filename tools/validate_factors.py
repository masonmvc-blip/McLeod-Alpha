from __future__ import annotations

import argparse
from pathlib import Path

from engine.factors import FactorRegistry, validate_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a populated in-memory factor registry and write deterministic metadata artifacts.")
    parser.add_argument("--output-root", default="artifacts/factors")
    args = parser.parse_args()
    registry = FactorRegistry()
    report = validate_registry(registry)
    registry.write_artifacts(Path(args.output_root), report)
    print(f"valid={report['valid']}")


if __name__ == "__main__":
    main()