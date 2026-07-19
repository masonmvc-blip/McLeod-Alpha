#!/usr/bin/env python3
"""
Historical backtest runner with optimization support.

Runs complete end-to-end backtest: load data → replay candles → generate signals →
simulate trades → analyze results.

Supports both single-backtest and multi-parameter optimization modes.

Outputs:
- backtesting/output/backtest_trades.csv - Trade log (single mode)
- backtesting/output/backtest_summary.json - Summary statistics (single mode)
- backtesting/output/strategy_comparison.csv - All combinations (optimize mode)
- backtesting/output/strategy_optimization.json - Top 10 results (optimize mode)
"""

import argparse
import sys
import json
from datetime import datetime
from pathlib import Path

from backtesting import load_csv_data, ReplayEngine
from backtesting.signal_replay import SignalReplayEngine
from backtesting.historical_option_playback import build_replay_option_pricer
from backtesting.trade_simulator import TradeSimulator
from backtesting.strategy_optimizer import StrategyOptimizer


def _parse_yyyy_mm_dd(value: str):
    """Argparse helper to parse YYYY-MM-DD into datetime.date."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected format: YYYY-MM-DD"
        ) from exc


def print_summary(summary: dict) -> None:
    """Print formatted summary statistics (single backtest mode)."""
    print("\n" + "="*80)
    print("BACKTEST SUMMARY")
    print("="*80)
    
    print(f"\nTOTAL TRADES:        {summary['total_trades']}")
    print(f"  Winners:          {summary['winners']}")
    print(f"  Losers:           {summary['losers']}")
    print(f"  Win Rate:         {summary['win_rate_pct']:.2f}%")
    
    print(f"\nP&L STATISTICS:")
    print(f"  Net P&L:          ${summary['net_pnl']:.2f}")
    print(f"  Gross Profit:     ${summary['gross_profit']:.2f}")
    print(f"  Gross Loss:       ${summary['gross_loss']:.2f}")
    print(f"  Avg Winner:       ${summary['avg_winner']:.2f}")
    print(f"  Avg Loser:        ${summary['avg_loser']:.2f}")
    print(f"  Profit Factor:    {summary['profit_factor']:.2f}")
    print(f"  Expectancy:       ${summary['expectancy']:.2f}")
    print(f"  Max Drawdown:     ${summary['max_drawdown']:.2f}")
    
    print(f"\nBY DIRECTION:")
    print(f"  CALL trades:      {summary['call_trades']} ({summary['call_winners']} winners)")
    print(f"  PUT trades:       {summary['put_trades']} ({summary['put_winners']} winners)")
    
    if summary.get('by_score'):
        print(f"\nBY ENTRY SCORE:")
        for score in sorted(summary['by_score'].keys(), key=lambda x: int(x)):
            stats = summary['by_score'][score]
            win_pct = (stats['wins'] / stats['count'] * 100) if stats['count'] > 0 else 0
            print(f"  Score {score}:      {stats['count']} trades ({stats['wins']} wins, {win_pct:.1f}%), ${stats['pnl']:.2f} P&L")
    
    if summary.get('by_exit_reason'):
        print(f"\nBY EXIT REASON:")
        for reason, stats in summary['by_exit_reason'].items():
            win_pct = (stats['wins'] / stats['count'] * 100) if stats['count'] > 0 else 0
            print(f"  {reason:20} {stats['count']:3} trades ({stats['wins']:2} wins, {win_pct:5.1f}%), ${stats['pnl']:8.2f}")
    
    if summary.get('by_regime'):
        print(f"\nBY MARKET REGIME:")
        for regime, stats in summary['by_regime'].items():
            win_pct = (stats['wins'] / stats['count'] * 100) if stats['count'] > 0 else 0
            print(f"  {regime:15} {stats['count']:3} trades ({stats['wins']:2} wins, {win_pct:5.1f}%), ${stats['pnl']:8.2f}")
    
    if summary.get('by_hour'):
        print(f"\nBY ENTRY HOUR (ET):")
        for hour in sorted(summary['by_hour'].keys()):
            stats = summary['by_hour'][hour]
            win_pct = (stats['wins'] / stats['count'] * 100) if stats['count'] > 0 else 0
            print(f"  {hour}           {stats['count']:3} trades ({stats['wins']:2} wins, {win_pct:5.1f}%), ${stats['pnl']:8.2f}")
    
    print(f"\nPRICING MODEL: {summary.get('pricing_model', 'ESTIMATED')}")
    print("="*80 + "\n")


def run_single_backtest(args) -> int:
    """Run a single backtest."""
    print("\n" + "="*80)
    print("HISTORICAL BACKTEST")
    print("="*80 + "\n")
    
    print("Configuration:")
    print(f"  Data file:            {args.data}")
    print(f"  Call threshold:       {args.call_threshold}")
    print(f"  Put threshold:        {args.put_threshold}")
    print(f"  Max hold (min):       {args.max_hold}")
    print(f"  Max trades/day:       {args.max_trades}")
    print(f"  Option delta:         {args.delta}")
    print(f"  Entry option price:   ${args.entry_option_price:.2f}")
    print(f"  Slippage:             ${args.slippage:.2f}")
    print(f"  Date from:            {args.date_from or 'All'}")
    print(f"  Date to:              {args.date_to or 'All'}")
    print(f"  Include premarket:    {args.include_premarket}")
    print(f"  Output CSV:           {args.output}")
    print("")
    
    try:
        # Load data
        print(f"Loading data from {args.data}...")
        df = load_csv_data(args.data)
        print(f"Loaded {len(df)} valid candles from {args.data}")
        
        # Initialize replay engine
        print(f"Initializing replay engine...")
        replay_engine = ReplayEngine(
            df,
            start_date=args.date_from,
            end_date=args.date_to,
            include_premarket=args.include_premarket
        )
        print(f"Replay engine initialized with {replay_engine.total_steps()} candles " +
              f"(premarket included: {args.include_premarket})")
        
        # Initialize signal engine
        print(f"Initializing signal replay engine...")
        signal_engine = SignalReplayEngine(
            replay_engine,
            call_threshold=args.call_threshold,
            put_threshold=args.put_threshold
        )
        
        # Initialize option pricer
        option_pricer = build_replay_option_pricer(
            entry_option_price=args.entry_option_price,
            delta=args.delta,
            slippage=args.slippage,
            trade_date=args.date_from if args.date_from == args.date_to else None,
        )
        
        # Initialize trade simulator
        print(f"Initializing trade simulator...")
        simulator = TradeSimulator(
            replay_engine=replay_engine,
            signal_engine=signal_engine,
            option_pricer=option_pricer,
            max_trades_per_day=args.max_trades,
            max_hold_minutes=args.max_hold,
        )
        
        # Run backtest
        print(f"Running backtest simulation...")
        trades = simulator.run()
        print(f"Simulation complete. Generated {len(trades)} trades.")
        
        # Export results
        print(f"\nExporting results...")
        
        # Create output directory
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Export trades CSV
        df_trades = simulator.get_trades_dataframe()
        df_trades.to_csv(output_path, index=False)
        print(f"✓ Exported {len(df_trades)} trades to {output_path}")
        
        # Export summary JSON
        summary = simulator.get_summary()
        summary_path = output_path.parent / "backtest_summary.json"
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"✓ Exported summary to {summary_path}")
        
        # Print summary
        print_summary(summary)
        
        return 0
    
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def run_optimization(args) -> int:
    """Run multi-parameter optimization."""
    print("\n" + "="*80)
    print("STRATEGY OPTIMIZATION")
    print("="*80 + "\n")
    
    print("Configuration:")
    print(f"  Data file:            {args.data}")
    print(f"  Call thresholds:      {args.call_thresholds}")
    print(f"  Put thresholds:       {args.put_thresholds}")
    print(f"  Max hold times:       {args.max_hold_times} minutes")
    print(f"  Max trades/day:       {args.max_trades}")
    print(f"  Total combinations:   {len(args.call_thresholds) * len(args.put_thresholds) * len(args.max_hold_times)}")
    print(f"  Option delta:         {args.delta}")
    print(f"  Entry option price:   ${args.entry_option_price:.2f}")
    print(f"  Slippage:             ${args.slippage:.2f}")
    print(f"  Date from:            {args.date_from or 'All'}")
    print(f"  Date to:              {args.date_to or 'All'}")
    print(f"  Include premarket:    {args.include_premarket}")
    print("")
    
    try:
        # Create optimizer
        optimizer = StrategyOptimizer(
            csv_path=args.data,
            call_thresholds=args.call_thresholds,
            put_thresholds=args.put_thresholds,
            max_hold_times=args.max_hold_times,
            max_trades_per_day=args.max_trades,
            date_from=args.date_from,
            date_to=args.date_to,
            include_premarket=args.include_premarket,
            delta=args.delta,
            entry_option_price=args.entry_option_price,
            slippage=args.slippage
        )
        
        # Run all combinations
        results = optimizer.run_all()
        print(f"\n✓ Optimization complete. Tested {len(results)} combinations.")
        
        # Export results
        output_dir = Path("backtesting/output")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Export comparison CSV
        csv_path = output_dir / "strategy_comparison.csv"
        df_results = optimizer.get_comparison_dataframe()
        df_results.to_csv(csv_path, index=False)
        print(f"\n✓ Exported {len(df_results)} results to {csv_path}")
        
        # Export optimization summary JSON
        json_path = output_dir / "strategy_optimization.json"
        summary_json = optimizer.get_summary_json()
        with open(json_path, 'w') as f:
            json.dump(summary_json, f, indent=2)
        print(f"✓ Exported optimization summary to {json_path}")
        
        # Print comparison table
        optimizer.print_comparison_table(n=10)
        
        return 0
    
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def main():
    """Main backtest entry point."""
    parser = argparse.ArgumentParser(
        description="Run historical backtest on SPY options strategy with optional optimization"
    )
    
    parser.add_argument(
        "--data",
        required=True,
        help="Path to historical OHLCV CSV data"
    )
    parser.add_argument(
        "--optimize",
        action="store_true",
        help="Run multi-parameter optimization instead of single backtest"
    )
    
    # Single backtest mode parameters
    parser.add_argument(
        "--call-threshold",
        type=int,
        default=5,
        help="Minimum CALL score for signal (default 5, ignored in --optimize mode)"
    )
    parser.add_argument(
        "--put-threshold",
        type=int,
        default=5,
        help="Minimum PUT score for signal (default 5, ignored in --optimize mode)"
    )
    
    # Optimization mode parameters
    parser.add_argument(
        "--call-thresholds",
        type=int,
        nargs="+",
        default=[4, 5, 6],
        help="List of call thresholds to test in --optimize mode (default 4 5 6)"
    )
    parser.add_argument(
        "--put-thresholds",
        type=int,
        nargs="+",
        default=[4, 5, 6],
        help="List of put thresholds to test in --optimize mode (default 4 5 6)"
    )
    
    # Common parameters
    parser.add_argument(
        "--max-hold",
        type=int,
        default=15,
        help="Maximum hold time in minutes for single mode (default 15)"
    )
    parser.add_argument(
        "--max-hold-times",
        type=int,
        nargs="+",
        default=[10, 15, 20],
        help="List of max hold times in minutes for --optimize mode (default 10 15 20)"
    )
    parser.add_argument(
        "--max-trades",
        type=int,
        default=20,
        help="Maximum trades per day (default 20)"
    )
    parser.add_argument(
        "--delta",
        type=float,
        default=0.45,
        help="Option delta sensitivity (default 0.45)"
    )
    parser.add_argument(
        "--entry-option-price",
        type=float,
        default=5.00,
        help="Simulated entry option price (default $5.00)"
    )
    parser.add_argument(
        "--slippage",
        type=float,
        default=0.04,
        help="Bid/ask slippage per contract (default $0.04)"
    )
    parser.add_argument(
        "--date-from",
        type=_parse_yyyy_mm_dd,
        help="Start date (YYYY-MM-DD), optional"
    )
    parser.add_argument(
        "--date-to",
        type=_parse_yyyy_mm_dd,
        help="End date (YYYY-MM-DD), optional"
    )
    parser.add_argument(
        "--include-premarket",
        action="store_true",
        help="Include premarket candles (for warming indicators)"
    )
    parser.add_argument(
        "--output",
        default="backtesting/output/backtest_trades.csv",
        help="Output CSV path for single mode (default backtesting/output/backtest_trades.csv)"
    )
    
    args = parser.parse_args()
    
    # Route to appropriate mode
    if args.optimize:
        return run_optimization(args)
    else:
        return run_single_backtest(args)


if __name__ == "__main__":
    sys.exit(main())

