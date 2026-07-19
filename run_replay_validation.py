#!/usr/bin/env python3
"""
Replay validation CLI runner.

Compares historical replay against known paper-trading results
for a specific date and produces detailed diagnostic reports.
"""

import sys
import json
import argparse
from pathlib import Path

from backtesting.replay_validation import (
    ReplayValidation,
    OptionPricerDiagnostics,
    FailureModeTests,
    print_comparison_report,
)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate historical replay against paper-trading results"
    )
    parser.add_argument(
        "--data",
        required=True,
        help="Path to historical OHLCV CSV"
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Validation date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--call-threshold",
        type=int,
        default=4,
        help="CALL threshold (default 4)"
    )
    parser.add_argument(
        "--put-threshold",
        type=int,
        default=4,
        help="PUT threshold (default 4)"
    )
    parser.add_argument(
        "--max-hold",
        type=int,
        default=15,
        help="Max hold minutes (default 15)"
    )
    parser.add_argument(
        "--max-trades",
        type=int,
        default=20,
        help="Max trades per day (default 20)"
    )
    parser.add_argument(
        "--delta",
        type=float,
        default=0.45,
        help="Option delta (default 0.45)"
    )
    parser.add_argument(
        "--entry-option-price",
        type=float,
        default=5.00,
        help="Entry option price (default $5.00)"
    )
    parser.add_argument(
        "--slippage",
        type=float,
        default=0.04,
        help="Slippage per contract (default $0.04)"
    )
    parser.add_argument(
        "--paper-trades",
        type=int,
        default=20,
        help="Paper trading trade count"
    )
    parser.add_argument(
        "--paper-winners",
        type=int,
        default=9,
        help="Paper trading winners"
    )
    parser.add_argument(
        "--paper-losers",
        type=int,
        default=11,
        help="Paper trading losers"
    )
    parser.add_argument(
        "--paper-net-pnl",
        type=float,
        default=-57.00,
        help="Paper trading net P&L"
    )
    parser.add_argument(
        "--paper-avg-hold",
        type=float,
        default=12.0,
        help="Paper trading average hold time in minutes"
    )
    parser.add_argument(
        "--paper-max-hold-exits",
        type=int,
        default=12,
        help="Paper trading MAX_HOLD exits"
    )
    parser.add_argument(
        "--paper-option-stop-exits",
        type=int,
        default=7,
        help="Paper trading OPTION_STOP exits"
    )
    parser.add_argument(
        "--paper-eod-exits",
        type=int,
        default=1,
        help="Paper trading END_OF_DAY_EXIT exits"
    )
    parser.add_argument(
        "--output-dir",
        default="backtesting/output",
        help="Output directory for reports"
    )
    parser.add_argument(
        "--paper-trade-log",
        default="today_trades.csv",
        help="CSV with paper trades (default today_trades.csv)"
    )
    
    args = parser.parse_args()
    
    print("\n" + "="*80)
    print("REPLAY VALIDATION RUNNER")
    print("="*80 + "\n")
    
    print("Configuration:")
    print(f"  Data file:            {args.data}")
    print(f"  Validation date:      {args.date}")
    print(f"  Call threshold:       {args.call_threshold}")
    print(f"  Put threshold:        {args.put_threshold}")
    print(f"  Max hold (min):       {args.max_hold}")
    print(f"  Max trades/day:       {args.max_trades}")
    print(f"  Option delta:         {args.delta}")
    print(f"  Entry option price:   ${args.entry_option_price:.2f}")
    print(f"  Slippage:             ${args.slippage:.2f}")
    print()
    
    print("Paper Trading Benchmark (2026-07-13):")
    print(f"  Trades:               {args.paper_trades}")
    print(f"  Winners:              {args.paper_winners}")
    print(f"  Losers:               {args.paper_losers}")
    print(f"  Win rate:             {args.paper_winners/args.paper_trades*100:.2f}%")
    print(f"  Net P&L:              ${args.paper_net_pnl:.2f}")
    print(f"  Avg hold (min):       {args.paper_avg_hold:.1f}")
    print()
    
    try:
        # Initialize validation
        print("Loading historical data...")
        validator = ReplayValidation(args.data, args.date)
        print(f"✓ Loaded {len(validator.df_day)} candles for {args.date}")
        
        # Run comparison
        print(f"\nRunning replay validation...")
        comparison = validator.compare_with_paper_trading(
            paper_trades=args.paper_trades,
            paper_winners=args.paper_winners,
            paper_losers=args.paper_losers,
            paper_net_pnl=args.paper_net_pnl,
            paper_avg_hold_min=args.paper_avg_hold,
            paper_max_hold_exits=args.paper_max_hold_exits,
            paper_option_stop_exits=args.paper_option_stop_exits,
            paper_eod_exits=args.paper_eod_exits,
        )
        
        # Print comparison
        print_comparison_report(comparison)
        
        # Test failure modes
        print("="*80)
        print("FAILURE MODE TESTS")
        print("="*80 + "\n")
        
        tests = [
            ("Option always decreasing", FailureModeTests.test_option_always_decreasing()),
            ("PUT decreases on rising SPY", FailureModeTests.test_put_decreases_on_rising_spy()),
            ("Slippage only at entry/exit", FailureModeTests.test_slippage_only_at_entry_exit()),
            ("Flat SPY not extreme loss", FailureModeTests.test_flat_spy_not_extreme_loss()),
            ("Favorable moves can win", FailureModeTests.test_favorable_move_can_win()),
        ]
        
        for test_name, result in tests:
            status = "✓ PASS" if result else "✗ FAIL"
            print(f"  {status}: {test_name}")
        
        print("\n" + "="*80 + "\n")
        
        # Export results
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save comparison to JSON
        comparison_json = {
            "validation_date": args.date,
            "comparisons": {k: v for k, v in comparison["comparisons"].items()},
            "all_match": comparison["all_match"],
            "mismatches": comparison["mismatches"],
        }
        
        json_path = output_dir / f"replay_validation_{args.date}.json"
        with open(json_path, 'w') as f:
            json.dump(comparison_json, f, indent=2)
        print(f"✓ Exported validation report to {json_path}")
        
        # Save text report
        txt_path = output_dir / f"replay_validation_{args.date}.txt"
        with open(txt_path, 'w') as f:
            f.write("="*80 + "\n")
            f.write("REPLAY VALIDATION REPORT\n")
            f.write(f"Date: {args.date}\n")
            f.write("="*80 + "\n\n")
            
            f.write("COMPARISON RESULTS:\n")
            comp = comparison["comparisons"]
            f.write(f"Trade count:     Paper={comp['trades']['paper']}  Replay={comp['trades']['replay']}  {'MATCH' if comp['trades']['match'] else 'MISMATCH'}\n")
            f.write(f"Winners:         Paper={comp['winners']['paper']}  Replay={comp['winners']['replay']}  {'MATCH' if comp['winners']['match'] else 'MISMATCH'}\n")
            f.write(f"Losers:          Paper={comp['losers']['paper']}  Replay={comp['losers']['replay']}  {'MATCH' if comp['losers']['match'] else 'MISMATCH'}\n")
            f.write(f"Win rate %:      Paper={comp['win_rate_pct']['paper']:.2f}%  Replay={comp['win_rate_pct']['replay']:.2f}%  {'MATCH' if comp['win_rate_pct']['match'] else 'MISMATCH'}\n")
            f.write(f"Net P&L:         Paper=${comp['net_pnl']['paper']:.2f}  Replay=${comp['net_pnl']['replay']:.2f}  {'MATCH' if comp['net_pnl']['match'] else 'MISMATCH'}\n\n")
            
            f.write("MISMATCHES:\n")
            if comparison["mismatches"]:
                for mismatch in comparison["mismatches"]:
                    f.write(f"  - {mismatch}\n")
            else:
                f.write("  None (all metrics match)\n")
            
            f.write("\n" + "="*80 + "\n")
        
        print(f"✓ Exported text report to {txt_path}")

        # Export per-trade parity table for the date
        try:
            parity_df = validator.compare_with_paper_trade_log(args.paper_trade_log)
            parity_path = output_dir / f"replay_trade_parity_{args.date}.csv"
            parity_df.to_csv(parity_path, index=False)
            print(f"✓ Exported per-trade parity table to {parity_path}")

            trace_df = validator.build_trade_trace_table(args.paper_trade_log)
            trace_path = output_dir / f"replay_trade_trace_{args.date}.csv"
            trace_df.to_csv(trace_path, index=False)
            print(f"✓ Exported minute-by-minute trace table to {trace_path}")
        except Exception as parity_exc:
            print(f"WARNING: could not build per-trade parity table: {parity_exc}")
        
        return 0
    
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
