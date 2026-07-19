from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.cio.pipeline import (
    CIOPipelineConflictError,
    CIOPipelineError,
    CIOPipelineValidationError,
    load_pipeline_inputs,
    run_cio_pipeline,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic CIO advisory pipeline")
    parser.add_argument("--input", required=True, help="Path to pipeline input JSON")
    parser.add_argument("--output-root", default=None, help="Override output root from input JSON")
    parser.add_argument("--validate-only", action="store_true", help="Validate input schema and exit")
    parser.add_argument("--print-summary", action="store_true", help="Print deterministic summary output")
    return parser


def _print_summary(*, run_id: str, overall_status: str, artifact_dir: str, blocker: str) -> None:
    print(f"run_id: {run_id}")
    print(f"overall_status: {overall_status}")
    print(f"artifact_directory: {artifact_dir}")
    print(f"first_blocker: {blocker}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    input_path = Path(args.input)

    try:
        inputs = load_pipeline_inputs(input_path, output_root_override=args.output_root)
    except CIOPipelineValidationError as exc:
        if args.print_summary:
            _print_summary(run_id="", overall_status="validation_failed", artifact_dir="", blocker=str(exc))
        else:
            print(str(exc))
        return 2

    run_id = "CIO-" + inputs.input_hash[:16].upper()
    artifact_dir = str(inputs.output_root / "artifacts" / "cio" / "runs" / run_id)

    if args.validate_only:
        if args.print_summary:
            _print_summary(run_id=run_id, overall_status="validated", artifact_dir=artifact_dir, blocker="")
        return 0

    try:
        result = run_cio_pipeline(inputs)
    except CIOPipelineConflictError as exc:
        if args.print_summary:
            _print_summary(run_id=run_id, overall_status="artifact_conflict", artifact_dir=artifact_dir, blocker=str(exc))
        else:
            print(str(exc))
        return 4
    except CIOPipelineError as exc:
        if args.print_summary:
            _print_summary(run_id=run_id, overall_status="failed", artifact_dir=artifact_dir, blocker=str(exc))
        else:
            print(str(exc))
        return 3

    if args.print_summary:
        blocker = ""
        for status in result.stage_statuses:
            if status.blocker:
                blocker = status.blocker
                break
        _print_summary(
            run_id=result.run_id,
            overall_status=result.overall_status,
            artifact_dir=artifact_dir,
            blocker=blocker,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
