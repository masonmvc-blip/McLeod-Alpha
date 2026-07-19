#!/usr/bin/env python3
"""
CLI runner for historical signal replay.

Loads historical data, replays through trading signals,
and exports results to CSV.

Usage:
  python run_signal_replay.py --data data/spy_1m.csv \\
    --call-threshold 5 --put-threshold 5 \\
    --date-from 2026-07-01 --date-to 2026-07-13
"""

import argparse
import sys
from pathlib import Path
from datetime import date

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backtesting.data_loader import load_csv_data
from backtesting.replay_engine import ReplayEngine
from backtesting.signal_replay import SignalReplayEngine


def parse_date(date_str: str) -> date:
    """Parse date string in format YYYY-MM-DD."""
    try:
        parts = date_str.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD")


def main():
    parser = argparse.ArgumentParser(
        description="Replay historical SPY candles and generate trading signals"
    )
    parser.add_argument(
        "--data",
        required=True,
        help="Path to CSV file with OHLCV data"
    )
    parser.add_argument(
        "--call-threshold",
        type=int,
        default=5,
        help="Minimum call score to qualify for entry (default: 5)"
    )
    parser.add_argument(
        "--put-threshold",
        type=int,
        default=5,
        help="Minimum put score to qualify for entry (default: 5)"
    )
    parser.add_argument(
        "--date-from",
        help="Start date (YYYY-MM-DD), inclusive"
    )
    parser.add_argument(
        "--date-to",
        help="End date (YYYY-MM-DD), inclusive"
    )
    parser.add_argument(
        "--output",
        help="Output CSV path (default: backtesting/output/signal_replay.csv)"
    )
    parser.add_argument(
        "--include-premarket",
        action="store_true",
        help="Include premarket candles for indicator warmup"
    )
    
    args = parser.parse_args()
    
    # Parse dates if provided
    start_date = None
    end_date = None
    if args.date_from:
        start_date = parse_date(args.date_from)
    if args.date_to:
        end_date = parse_date(args.date_to)
    
    # Set default output path
    output_path = args.output
    if not output_path:
        output_dir = Path("backtesting/output")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / "signal_replay.csv")
    
    print("\n" + "="*80)
    print("HISTORICAL SIGNAL REPLAY")
    print("="*80)
    print(f"\nConfiguration:")
    print(f"  Data file:          {args.data}")
    print(f"  Call threshold:     {args.call_threshold}")
    print(f"  Put threshold:      {args.put_threshold}")
    print(f"  Date from:          {start_date or 'All available'}")
    print(f"  Date to:            {end_date or 'All available'}")
    print(f"  Include premarket:  {args.include_premarket}")
    print(f"  Output CSV:         {output_path}")
    
    try:
        # Load data
        print(f"\nLoading data from {args.data}...")
        df = load_csv_data(args.data)
        
        # Create replay engine
        print(f"Initializing replay engine ({df.shape[0]} candles)...")
        engine = ReplayEngine(
            df,
            start_date=start_date,
            end_date=end_date,
            include_premarket=args.include_premarket
        )
        
        # Create signal replay engine
        signal_engine = SignalReplayEngine(
            engine,
            call_threshold=args.call_threshold,
            put_threshold=args.put_threshold
        )
        
        # Replay and generate signals
        print(f"Replaying {engine.total_steps()} candles...")
        signals = signal_engine.replay()
        
        # Get summary
        summary = signal_engine.get_summary()
        
        # Print summary
        print("\n" + "-"*80)
        print("SIGNAL REPLAY SUMMARY")
        print("-"*80)
        print(f"Total candles evaluated:         {summary['total_candles_evaluated']}")
        print(f"Regular session candles:         {summary['regular_session_candles']}")
        print(f"CALL-qualified signals:          {summary['call_qualified_signals']}")
        print(f"PUT-qualified signals:           {summary['put_qualified_signals']}")
        
        if summary['signals_by_score']:
            print(f"\nSignals by score:")
            for score in sorted(summary['signals_by_score'].keys()):
                count = summary['signals_by_score'][score]
                print(f"  Score {score}: {count} signals")
        
        if summary['signals_by_hour']:
            print(f"\nSignals by hour (ET):")
            for hour in sorted(summary['signals_by_hour'].keys()):
                data = summary['signals_by_hour'][hour]
                print(f"  {hour:02d}:00 - CALL: {data['calls']:3d} | PUT: {data['puts']:3d}")
        
        if summary['signals_by_regime']:
            print(f"\nSignals by market regime:")
            for regime in sorted(summary['signals_by_regime'].keys()):
                data = summary['signals_by_regime'][regime]
                print(f"  {regime:15s} - CALL: {data['calls']:3d} | PUT: {data['puts']:3d}")
        
        # Export to CSV
        print(f"\nExporting {len(signals)} signals to {output_path}...")
        df_output = signal_engine.to_dataframe()
        
        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df_output.to_csv(output_path, index=False)
        
        print(f"✓ Exported to {output_path}")
        print(f"\nColumns in output CSV:")
        for col in df_output.columns:
            print(f"  • {col}")
        
        print("\n" + "="*80)
        print("✓ SIGNAL REPLAY COMPLETE")
        print("="*80 + "\n")
        
        return 0
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
