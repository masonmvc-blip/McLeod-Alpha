"""Import external CSV, JSON, and JSONL historical records into deterministic raw_sources."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.importers import AnalystImporter, FundamentalsImporter, MacroImporter, NewsImporter, PriceImporter, SECImporter, UniverseImporter
from engine.importers.import_contract import ImportValidationError, import_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = import_all(input_root=args.input, output_root=args.output, importers=(SECImporter(), PriceImporter(), FundamentalsImporter(), MacroImporter(), AnalystImporter(), NewsImporter(), UniverseImporter()))
        print(f"imported_records={report.imported_records}")
        print(f"rejected_records={report.rejected_records}")
        print(f"output_path={args.output}")
        return 0
    except ImportValidationError as exc:
        print(str(exc), file=sys.stderr)
        print(str(exc.report.to_dict()), file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())