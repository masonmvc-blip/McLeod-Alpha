#!/usr/bin/env python3
"""Run Phase 1 research pipeline for the McLeod Alpha canonical ticker set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.research_phase1 import INITIAL_TICKERS, run_phase1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1 research collector/parser/fact-store pipeline")
    parser.add_argument(
        "--tickers",
        nargs="*",
        default=list(INITIAL_TICKERS),
        help="Tickers to process (default: Phase 1 canonical set)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tickers: List[str] = [str(t).upper().strip() for t in args.tickers if str(t).strip()]
    result = run_phase1(tickers=tickers)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
