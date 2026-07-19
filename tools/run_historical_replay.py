from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.replay.replay_engine import run_replay_engine
from engine.replay.replay_runner import ReplayIntegrityError, ReplayLookaheadError
from engine.replay.snapshot_loader import SnapshotValidationError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic historical replay for the CIO advisory stack.")
    parser.add_argument(
        "--snapshot-root",
        default="artifacts/replay/snapshots",
        help="Directory containing historical snapshot JSON files.",
    )
    parser.add_argument(
        "--output-root",
        default="artifacts/replay",
        help="Output directory for replay artifacts.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run replay but skip writing artifacts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = run_replay_engine(
            snapshot_root=Path(args.snapshot_root),
            output_root=Path(args.output_root),
            write_artifacts=not bool(args.validate_only),
        )
    except SnapshotValidationError as exc:
        print(f"Snapshot validation error: {exc}")
        return 3
    except ReplayLookaheadError as exc:
        print(f"Lookahead protection failure: {exc}")
        return 2
    except ReplayIntegrityError as exc:
        print(f"Replay integrity error: {exc}")
        return 4
    except Exception as exc:  # pragma: no cover
        print(f"Unexpected replay failure: {exc}")
        return 5

    print(f"replay_id: {result.replay.replay_id}")
    print(f"snapshot_count: {result.replay.snapshot_count}")
    print(f"content_hash: {result.replay.content_hash}")
    print(f"report_path: {result.report_path if not args.validate_only else ''}")
    print(f"decision_stability: {result.replay.metrics.decision_stability:.6f}")
    print(f"recommendation_changes: {result.replay.metrics.recommendation_changes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
