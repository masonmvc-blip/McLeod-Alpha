#!/usr/bin/env python3
"""Run full backtest with Alpaca historical option trades only."""

from __future__ import annotations

import argparse
import json
import sys

from backtesting.alpaca_full_backtest import run_alpaca_full_backtest


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Alpaca historical option-trade full backtest")
    parser.add_argument("--data", required=True, help="Path to SPY 1-minute CSV")
    parser.add_argument("--call-threshold", type=int, default=5)
    parser.add_argument("--put-threshold", type=int, default=5)
    parser.add_argument("--max-hold", type=int, default=15)
    parser.add_argument("--max-trades", type=int, default=20)
    parser.add_argument("--cache-root", default="data/historical/options/alpaca")
    parser.add_argument("--output-dir", default="backtesting/output")
    args = parser.parse_args()

    print("=" * 80)
    print("ALPACA FULL BACKTEST")
    print("=" * 80)
    print(f"Data: {args.data}")
    print(f"Thresholds: CALL={args.call_threshold}, PUT={args.put_threshold}")
    print(f"Max hold: {args.max_hold} minutes")
    print(f"Max trades/day: {args.max_trades}")
    print(f"Cache root: {args.cache_root}")
    print(f"Output dir: {args.output_dir}")

    result = run_alpaca_full_backtest(
        spy_csv_path=args.data,
        call_threshold=args.call_threshold,
        put_threshold=args.put_threshold,
        max_hold_minutes=args.max_hold,
        max_trades_per_day=args.max_trades,
        cache_root=args.cache_root,
        output_dir=args.output_dir,
    )

    print("\nSummary:")
    print(json.dumps(result["summary"], indent=2))

    print("\nOutput files:")
    for k, v in result["files"].items():
        print(f"- {k}: {v}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
