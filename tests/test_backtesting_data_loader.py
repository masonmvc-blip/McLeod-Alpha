"""
Comprehensive tests for backtesting data loader and replay engine.

Tests:
- Missing columns are rejected
- Duplicate timestamps are removed
- Rows are sorted correctly
- Invalid OHLC rows are rejected
- Negative volume is rejected
- Timezone conversion works
- Premarket, regular, and after-hours candles are labeled correctly
- Replay never exposes a future candle
- Date filtering works
"""

import sys
import tempfile
import pandas as pd
from datetime import datetime, date, time as dt_time
from zoneinfo import ZoneInfo
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtesting.data_loader import (
    load_csv_data,
    validate_dataframe,
    classify_candle,
    TIMEZONE
)
from backtesting.replay_engine import ReplayEngine


def create_test_csv(rows, csv_path):
    """Helper to create test CSV."""
    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False)


def test_missing_columns():
    """Test that missing columns are rejected."""
    print("\n" + "="*70)
    print("TEST: Missing columns rejection")
    print("="*70)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        # Missing 'high' column
        f.write("timestamp,open,low,close,volume\n")
        f.write("2026-07-13 09:30:00,100.0,99.5,100.5,1000\n")
        csv_path = f.name
    
    try:
        load_csv_data(csv_path)
        print("✗ FAILED: Should have rejected missing column")
        return False
    except ValueError as e:
        if "Missing required columns" in str(e):
            print(f"✓ PASSED: Correctly rejected - {e}")
            return True
        else:
            print(f"✗ FAILED: Wrong error - {e}")
            return False
    finally:
        Path(csv_path).unlink()


def test_duplicate_timestamps():
    """Test that duplicate timestamps are removed."""
    print("\n" + "="*70)
    print("TEST: Duplicate timestamp removal")
    print("="*70)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("timestamp,open,high,low,close,volume\n")
        f.write("2026-07-13 09:30:00,100.0,100.5,99.5,100.2,1000\n")
        f.write("2026-07-13 09:30:00,100.1,100.6,99.4,100.3,1100\n")  # Duplicate
        f.write("2026-07-13 09:31:00,100.2,100.7,99.3,100.4,1200\n")
        csv_path = f.name
    
    try:
        df = load_csv_data(csv_path)
        if len(df) == 2:  # Only 2 unique timestamps
            print(f"✓ PASSED: Duplicates removed, {len(df)} candles remaining")
            return True
        else:
            print(f"✗ FAILED: Expected 2 candles, got {len(df)}")
            return False
    finally:
        Path(csv_path).unlink()


def test_sorted_chronologically():
    """Test that rows are sorted chronologically."""
    print("\n" + "="*70)
    print("TEST: Chronological sorting")
    print("="*70)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("timestamp,open,high,low,close,volume\n")
        f.write("2026-07-13 09:31:00,100.2,100.7,99.3,100.4,1200\n")
        f.write("2026-07-13 09:30:00,100.0,100.5,99.5,100.2,1000\n")  # Out of order
        f.write("2026-07-13 09:32:00,100.3,100.8,99.2,100.5,1300\n")
        csv_path = f.name
    
    try:
        df = load_csv_data(csv_path)
        is_sorted = df["timestamp"].is_monotonic_increasing
        if is_sorted:
            print(f"✓ PASSED: Data sorted correctly")
            print(f"  First: {df.iloc[0]['timestamp']}")
            print(f"  Last:  {df.iloc[-1]['timestamp']}")
            return True
        else:
            print(f"✗ FAILED: Data not sorted")
            return False
    finally:
        Path(csv_path).unlink()


def test_invalid_ohlc_high_less_than_low():
    """Test that high < low is rejected."""
    print("\n" + "="*70)
    print("TEST: Invalid OHLC - high < low rejection")
    print("="*70)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("timestamp,open,high,low,close,volume\n")
        f.write("2026-07-13 09:30:00,100.0,99.0,100.5,100.2,1000\n")  # high < low
        f.write("2026-07-13 09:31:00,100.0,100.5,99.5,100.2,1000\n")  # Valid
        csv_path = f.name
    
    try:
        df = load_csv_data(csv_path)
        if len(df) == 1:  # Only valid row
            print(f"✓ PASSED: Invalid row rejected, {len(df)} valid row remains")
            return True
        else:
            print(f"✗ FAILED: Expected 1 valid row, got {len(df)}")
            return False
    finally:
        Path(csv_path).unlink()


def test_invalid_ohlc_high_less_than_open():
    """Test that high < open is rejected."""
    print("\n" + "="*70)
    print("TEST: Invalid OHLC - high < open rejection")
    print("="*70)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("timestamp,open,high,low,close,volume\n")
        f.write("2026-07-13 09:30:00,100.5,100.0,99.5,100.2,1000\n")  # high < open
        f.write("2026-07-13 09:31:00,100.0,100.5,99.5,100.2,1000\n")  # Valid
        csv_path = f.name
    
    try:
        df = load_csv_data(csv_path)
        if len(df) == 1:
            print(f"✓ PASSED: Invalid row rejected")
            return True
        else:
            print(f"✗ FAILED: Expected 1 valid row, got {len(df)}")
            return False
    finally:
        Path(csv_path).unlink()


def test_invalid_ohlc_low_greater_than_open():
    """Test that low > open is rejected."""
    print("\n" + "="*70)
    print("TEST: Invalid OHLC - low > open rejection")
    print("="*70)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("timestamp,open,high,low,close,volume\n")
        f.write("2026-07-13 09:30:00,100.0,100.5,100.1,100.2,1000\n")  # low > open
        f.write("2026-07-13 09:31:00,100.0,100.5,99.5,100.2,1000\n")  # Valid
        csv_path = f.name
    
    try:
        df = load_csv_data(csv_path)
        if len(df) == 1:
            print(f"✓ PASSED: Invalid row rejected")
            return True
        else:
            print(f"✗ FAILED: Expected 1 valid row, got {len(df)}")
            return False
    finally:
        Path(csv_path).unlink()


def test_negative_volume():
    """Test that negative volume is rejected."""
    print("\n" + "="*70)
    print("TEST: Negative volume rejection")
    print("="*70)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("timestamp,open,high,low,close,volume\n")
        f.write("2026-07-13 09:30:00,100.0,100.5,99.5,100.2,-100\n")  # Negative
        f.write("2026-07-13 09:31:00,100.0,100.5,99.5,100.2,1000\n")  # Valid
        csv_path = f.name
    
    try:
        df = load_csv_data(csv_path)
        if len(df) == 1:
            print(f"✓ PASSED: Negative volume rejected")
            return True
        else:
            print(f"✗ FAILED: Expected 1 valid row, got {len(df)}")
            return False
    finally:
        Path(csv_path).unlink()


def test_timezone_conversion():
    """Test timezone conversion to America/New_York."""
    print("\n" + "="*70)
    print("TEST: Timezone conversion to America/New_York")
    print("="*70)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("timestamp,open,high,low,close,volume\n")
        f.write("2026-07-13 13:30:00,100.0,100.5,99.5,100.2,1000\n")  # Interpreted as UTC
        csv_path = f.name
    
    try:
        df = load_csv_data(csv_path)
        tz = df["timestamp"].iloc[0].tzinfo
        
        if tz and "America/New_York" in str(tz):
            print(f"✓ PASSED: Timezone correctly set to {tz}")
            print(f"  Timestamp: {df['timestamp'].iloc[0]}")
            return True
        else:
            print(f"✗ FAILED: Timezone is {tz}")
            return False
    finally:
        Path(csv_path).unlink()


def test_candle_classification():
    """Test PREMARKET, REGULAR, AFTER_HOURS classification."""
    print("\n" + "="*70)
    print("TEST: Candle classification (PREMARKET, REGULAR, AFTER_HOURS)")
    print("="*70)
    
    # Create test timestamps in America/New_York
    premarket = datetime(2026, 7, 13, 9, 0, tzinfo=TIMEZONE)
    regular_open = datetime(2026, 7, 13, 9, 30, tzinfo=TIMEZONE)
    regular_mid = datetime(2026, 7, 13, 12, 0, tzinfo=TIMEZONE)
    after_hours = datetime(2026, 7, 13, 16, 30, tzinfo=TIMEZONE)
    
    results = []
    
    # Test premarket
    result = classify_candle(premarket)
    expected = "PREMARKET"
    passed = result == expected
    results.append(passed)
    print(f"  Premarket (9:00 AM):   {result:15s} {'✓' if passed else '✗'}")
    
    # Test regular open
    result = classify_candle(regular_open)
    expected = "REGULAR"
    passed = result == expected
    results.append(passed)
    print(f"  Regular (9:30 AM):     {result:15s} {'✓' if passed else '✗'}")
    
    # Test regular mid
    result = classify_candle(regular_mid)
    expected = "REGULAR"
    passed = result == expected
    results.append(passed)
    print(f"  Regular (12:00 PM):    {result:15s} {'✓' if passed else '✗'}")
    
    # Test after-hours
    result = classify_candle(after_hours)
    expected = "AFTER_HOURS"
    passed = result == expected
    results.append(passed)
    print(f"  After-hours (4:30 PM): {result:15s} {'✓' if passed else '✗'}")
    
    if all(results):
        print("✓ PASSED: All classifications correct")
        return True
    else:
        print("✗ FAILED: Some classifications incorrect")
        return False


def test_replay_no_future_candles():
    """Test that replay never exposes a future candle."""
    print("\n" + "="*70)
    print("TEST: Replay never exposes future candles")
    print("="*70)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("timestamp,open,high,low,close,volume\n")
        # UTC times that will be regular market hours when converted to ET
        # UTC 13:30 = ET 09:30, etc.
        for i in range(10):
            ts = f"2026-07-13 13:{30+i:02d}:00"  # UTC times
            f.write(f"{ts},100.0,100.5,99.5,100.2,1000\n")
        csv_path = f.name
    
    try:
        df = load_csv_data(csv_path)
        engine = ReplayEngine(df, include_premarket=True)  # Include premarket for this test
        
        all_valid = True
        for step in range(engine.total_steps()):
            # Verify step is valid
            if not engine.verify_no_future_candles(step):
                all_valid = False
                print(f"  ✗ Step {step} exposed future candles")
                break
            
            # Verify candles count
            exposed = engine.get_candles_up_to_step(step)
            if len(exposed) != step + 1:
                all_valid = False
                print(f"  ✗ Step {step}: expected {step+1} candles, got {len(exposed)}")
                break
        
        if all_valid:
            print(f"✓ PASSED: Verified {engine.total_steps()} steps - no future candles exposed")
            return True
        else:
            print("✗ FAILED: Future candles were exposed")
            return False
    finally:
        Path(csv_path).unlink()


def test_date_range_filtering():
    """Test date range filtering."""
    print("\n" + "="*70)
    print("TEST: Date range filtering")
    print("="*70)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("timestamp,open,high,low,close,volume\n")
        f.write("2026-07-12 13:30:00,100.0,100.5,99.5,100.2,1000\n")  # UTC, ET: 07-12 09:30
        f.write("2026-07-13 13:30:00,100.0,100.5,99.5,100.2,1000\n")  # UTC, ET: 07-13 09:30
        f.write("2026-07-13 14:00:00,100.0,100.5,99.5,100.2,1000\n")  # UTC, ET: 07-13 10:00
        f.write("2026-07-14 13:30:00,100.0,100.5,99.5,100.2,1000\n")  # UTC, ET: 07-14 09:30
        csv_path = f.name
    
    try:
        df = load_csv_data(csv_path)
        
        # Filter to 2026-07-13 only
        engine = ReplayEngine(
            df,
            start_date=date(2026, 7, 13),
            end_date=date(2026, 7, 13),
            include_premarket=True  # Include premarket for this test
        )
        
        if engine.total_steps() == 2:  # Should have 2 candles on 07-13
            print(f"✓ PASSED: Date filtering works, {engine.total_steps()} candles on target date")
            start, end = engine.get_date_range()
            print(f"  Date range: {start} to {end}")
            return True
        else:
            print(f"✗ FAILED: Expected 2 candles, got {engine.total_steps()}")
            return False
    finally:
        Path(csv_path).unlink()


def test_premarket_filtering():
    """Test premarket candle inclusion/exclusion."""
    print("\n" + "="*70)
    print("TEST: Premarket candle filtering")
    print("="*70)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("timestamp,open,high,low,close,volume\n")
        f.write("2026-07-13 13:00:00,100.0,100.5,99.5,100.2,1000\n")  # UTC, ET: 09:00 (Premarket)
        f.write("2026-07-13 13:30:00,100.0,100.5,99.5,100.2,1000\n")  # UTC, ET: 09:30 (Regular)
        f.write("2026-07-13 14:00:00,100.0,100.5,99.5,100.2,1000\n")  # UTC, ET: 10:00 (Regular)
        csv_path = f.name
    
    try:
        df = load_csv_data(csv_path)
        
        # With premarket
        engine_with = ReplayEngine(df, include_premarket=True)
        count_with = engine_with.total_steps()
        
        # Without premarket
        engine_without = ReplayEngine(df, include_premarket=False)
        count_without = engine_without.total_steps()
        
        if count_with == 3 and count_without == 2:
            print(f"✓ PASSED: Premarket filtering works")
            print(f"  With premarket:    {count_with} candles")
            print(f"  Without premarket: {count_without} candles")
            return True
        else:
            print(f"✗ FAILED: Expected 3 and 2, got {count_with} and {count_without}")
            return False
    finally:
        Path(csv_path).unlink()


def test_validate_dataframe():
    """Test DataFrame validation function."""
    print("\n" + "="*70)
    print("TEST: DataFrame validation")
    print("="*70)
    
    # Valid DataFrame
    valid_df = pd.DataFrame({
        "timestamp": pd.date_range("2026-07-13", periods=3, freq="1min", tz=TIMEZONE),
        "open": [100.0, 100.1, 100.2],
        "high": [100.5, 100.6, 100.7],
        "low": [99.5, 99.6, 99.7],
        "close": [100.2, 100.3, 100.4],
        "volume": [1000, 1100, 1200]
    })
    
    # Invalid DataFrame (not sorted)
    invalid_df = valid_df.iloc[[2, 0, 1]]
    
    valid_check = validate_dataframe(valid_df)
    invalid_check = validate_dataframe(invalid_df)
    
    if valid_check and not invalid_check:
        print(f"✓ PASSED: Valid DataFrame accepted, invalid rejected")
        return True
    else:
        print(f"✗ FAILED: valid={valid_check}, invalid={invalid_check}")
        return False


def run_all_tests():
    """Run all tests and report results."""
    print("\n" + "="*70)
    print("BACKTESTING DATA LOADER & REPLAY ENGINE - TEST SUITE")
    print("="*70)
    
    tests = [
        ("Missing columns", test_missing_columns),
        ("Duplicate timestamps", test_duplicate_timestamps),
        ("Chronological sorting", test_sorted_chronologically),
        ("Invalid OHLC (high < low)", test_invalid_ohlc_high_less_than_low),
        ("Invalid OHLC (high < open)", test_invalid_ohlc_high_less_than_open),
        ("Invalid OHLC (low > open)", test_invalid_ohlc_low_greater_than_open),
        ("Negative volume", test_negative_volume),
        ("Timezone conversion", test_timezone_conversion),
        ("Candle classification", test_candle_classification),
        ("Replay no future candles", test_replay_no_future_candles),
        ("Date range filtering", test_date_range_filtering),
        ("Premarket filtering", test_premarket_filtering),
        ("DataFrame validation", test_validate_dataframe),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"\n✗ EXCEPTION in {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    print("="*70)
    
    return all(results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
