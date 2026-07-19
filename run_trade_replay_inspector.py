#!/usr/bin/env python3
"""CLI runner for backtesting trade replay inspector."""

import argparse
from pathlib import Path

from backtesting.trade_replay_inspector import PaperTradeSpec, inspect_trade


def main() -> int:
    parser = argparse.ArgumentParser(description="Run minute-by-minute replay inspector for a paper trade")
    parser.add_argument("--data", required=True, help="Path to historical OHLCV CSV")
    parser.add_argument("--date", required=True, help="Trade date YYYY-MM-DD")
    parser.add_argument("--entry-time", required=True, help="Paper entry time HH:MM:SS")
    parser.add_argument("--direction", required=True, choices=["CALL", "PUT", "call", "put"], help="Trade direction")
    parser.add_argument("--paper-exit-time", required=True, help="Paper exit time HH:MM:SS")
    parser.add_argument("--paper-pnl", required=True, type=float, help="Paper option P/L in dollars")
    parser.add_argument("--paper-return", required=True, type=float, help="Paper option return in percent")
    parser.add_argument("--paper-exit-reason", default="OPTION_STOP", help="Paper exit reason")

    args = parser.parse_args()

    out_dir = Path("backtesting/output")
    out_csv = out_dir / f"trade_replay_inspector_{args.date}_trade4.csv"
    out_txt = out_dir / f"trade_replay_inspector_{args.date}_trade4.txt"

    spec = PaperTradeSpec(
        data_path=Path(args.data),
        trade_date=args.date,
        entry_time=args.entry_time,
        direction=args.direction,
        paper_exit_time=args.paper_exit_time,
        paper_pnl=args.paper_pnl,
        paper_return=args.paper_return,
        paper_exit_reason=args.paper_exit_reason,
    )

    result = inspect_trade(spec=spec, out_csv_path=out_csv, out_txt_path=out_txt)
    summary = result["summary"]

    print("Paper result")
    print(summary["paper_result"])
    print("Replay result")
    print(summary["replay_result"])
    print(f"First divergence timestamp: {summary['first_divergence_timestamp']}")
    print(f"First divergent field: {summary['first_divergent_field']}")
    print(f"Replay exited too early: {summary['replay_exited_too_early']}")
    print(f"Replay exit price too low: {summary['replay_exit_price_too_low']}")
    print(f"Stop logic differed: {summary['stop_logic_differed']}")
    print(f"Slippage/time decay over-applied: {summary['slippage_or_time_decay_overapplied']}")
    print(f"Most likely root cause: {summary['most_likely_root_cause']}")

    print("Output files")
    print(out_csv)
    print(out_txt)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
