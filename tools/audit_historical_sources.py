"""CLI for deterministic historical raw-source coverage audits."""

from __future__ import annotations

import argparse
from typing import Sequence

from engine.data_quality import ArtifactConflictError, AuditInputError, audit_historical_sources


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--frequency", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--universe-file")
    parser.add_argument("--report-only-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = audit_historical_sources(source_root=args.source_root, policy_path=args.policy, symbols=args.symbols.split(","), start_date=args.start_date, end_date=args.end_date, frequency=args.frequency, output_root=args.output_root, universe_file=args.universe_file, report_only_failures=args.report_only_failures)
    except AuditInputError:
        return 4
    except ArtifactConflictError:
        return 5
    except Exception:
        return 6
    print(f"audit_id={result.audit_id}")
    print(f"status={result.status}")
    print(f"symbols_ready={','.join(result.symbols_ready)}")
    print(f"symbols_partial={','.join(result.symbols_partial)}")
    print(f"symbols_not_ready={','.join(result.symbols_not_ready)}")
    print(f"lookahead_failures={len(result.lookahead_failures)}")
    print(f"output_path={result.output_path}")
    return {"READY": 0, "PARTIAL": 1, "NOT_READY": 2, "LOOKAHEAD_FAILURE": 3}[result.status]


if __name__ == "__main__":
    raise SystemExit(main())