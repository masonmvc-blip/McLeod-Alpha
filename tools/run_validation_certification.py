from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.validation.certification_gate import (
    ValidationCertificationConflictError,
    ValidationCertificationError,
    ValidationCertificationInputError,
    evaluate_validation_certification,
)
from engine.validation.certification_policy import (
    ValidationCertificationPolicyError,
    load_validation_certification_policy,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Validation Certification Gate")
    parser.add_argument("--validation-input", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--system-version", required=True)
    parser.add_argument("--output-root", default=".")
    parser.add_argument("--print-summary", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    return parser


def _print_summary(*, certification_id: str, status: str, eligible: bool, artifact_directory: str, first_blocker: str) -> None:
    print(f"certification_id: {certification_id}")
    print(f"status: {status}")
    print(f"eligible_for_paper_trading: {str(eligible).lower()}")
    print(f"artifact_directory: {artifact_directory}")
    print(f"first_blocker: {first_blocker}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        policy = load_validation_certification_policy(Path(args.policy))
        payload = json.loads(Path(args.validation_input).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValidationCertificationInputError("validation-input JSON must be an object")
    except (ValidationCertificationPolicyError, ValidationCertificationInputError, FileNotFoundError, json.JSONDecodeError) as exc:
        if args.print_summary:
            _print_summary(certification_id="", status="FAIL", eligible=False, artifact_directory="", first_blocker=str(exc))
        else:
            print(str(exc))
        return 3

    try:
        result = evaluate_validation_certification(
            policy=policy,
            validation_input_payload=payload,
            system_version=args.system_version,
            output_root=Path(args.output_root),
            write_artifacts=not args.validate_only,
        )
    except ValidationCertificationConflictError as exc:
        if args.print_summary:
            _print_summary(certification_id="", status="FAIL", eligible=False, artifact_directory="", first_blocker=str(exc))
        else:
            print(str(exc))
        return 4
    except ValidationCertificationError as exc:
        if args.print_summary:
            _print_summary(certification_id="", status="FAIL", eligible=False, artifact_directory="", first_blocker=str(exc))
        else:
            print(str(exc))
        return 5
    except Exception as exc:  # pragma: no cover
        if args.print_summary:
            _print_summary(certification_id="", status="FAIL", eligible=False, artifact_directory="", first_blocker=str(exc))
        else:
            print(str(exc))
        return 5

    artifact_dir = ""
    if result.artifact_paths:
        artifact_dir = str(Path(result.artifact_paths[0]).parent)

    if args.print_summary:
        _print_summary(
            certification_id=result.certification_id,
            status=result.status,
            eligible=result.eligible_for_paper_trading,
            artifact_directory=artifact_dir,
            first_blocker=result.first_blocker,
        )

    if result.status == "PASS":
        return 0
    if result.status == "CONDITIONAL_PASS":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
