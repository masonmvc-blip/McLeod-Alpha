"""Build an immutable Historical Time Machine dataset from JSON input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.datasets import DatasetBuilder  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON file containing dataset_id, dataset_name, market, snapshots, and optional expected_dates")
    parser.add_argument("--output", required=True, type=Path, help="Output dataset directory")
    args = parser.parse_args()
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    DatasetBuilder().build(
        output_dir=args.output,
        dataset_id=raw["dataset_id"],
        dataset_name=raw["dataset_name"],
        market=raw["market"],
        snapshots=raw["snapshots"],
        expected_dates=raw.get("expected_dates"),
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())