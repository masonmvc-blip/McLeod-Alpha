"""Build deterministic historical datasets exclusively from local JSON/JSONL sources."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.data_sources.source_contract import SourceValidationError
from engine.datasets.dataset_assembler import DatasetAssembler
from engine.datasets.dataset_schema import CREATION_VERSION, SCHEMA_VERSION, DatasetSchemaError, parse_date
from engine.datasets.dataset_validator import DatasetValidationError


def _dates_from_args(args: argparse.Namespace) -> tuple[str, ...]:
    if args.dates_file:
        return tuple(sorted({parse_date(line.strip(), field_name="dates-file").isoformat() for line in args.dates_file.read_text(encoding="utf-8").splitlines() if line.strip()}))
    start, end = parse_date(args.start_date, field_name="start-date"), parse_date(args.end_date, field_name="end-date")
    if end < start:
        raise SourceValidationError("end-date must not be before start-date")
    dates: list[str] = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return tuple(dates)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--market", required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--dates-file", type=Path)
    parser.add_argument("--schema-version", default=SCHEMA_VERSION)
    parser.add_argument("--creation-version", default=CREATION_VERSION)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.schema_version != SCHEMA_VERSION or args.creation_version != CREATION_VERSION:
            raise SourceValidationError("unsupported schema-version or creation-version")
        dates = _dates_from_args(args)
        symbols = tuple(part.strip() for part in args.symbols.split(",") if part.strip())
        assembler = DatasetAssembler()
        snapshots = assembler.assemble_snapshots(dates=dates, symbols=symbols, source_root=args.source_root)
        content_hash = assembler.preview_content_hash(dataset_id=args.dataset_id, dataset_name=args.dataset_name, market=args.market, snapshots=snapshots, expected_dates=dates)
        if not args.validate_only:
            assembler.build(output_dir=args.output, dataset_id=args.dataset_id, dataset_name=args.dataset_name, market=args.market, dates=dates, symbols=symbols, source_root=args.source_root)
        print(f"dataset_id={args.dataset_id}")
        print(f"snapshot_count={len(snapshots)}")
        print(f"content_hash={content_hash}")
        print(f"output_path={args.output}")
        return 0
    except (SourceValidationError, DatasetSchemaError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except DatasetValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())