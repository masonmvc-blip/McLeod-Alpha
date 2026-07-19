#!/usr/bin/env python3
"""
Verification test for trade_log field population.
Simulates a trade being logged to verify all option fields are present.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import sys

def test_trade_log_fields():
    """Test that all option fields are populated when logging a trade."""
    
    # Create a test database
    test_db = Path("test_trade_verification.db")
    if test_db.exists():
        test_db.unlink()
    
    print("Testing trade_log field population...")
    print("=" * 60)
    
    # Import the trade logger
    sys.path.insert(0, str(Path("execution").resolve()))
    from trade_logger import log_trade
    
    # Simulate a trade with all option fields populated
    entry_time = datetime.now() - timedelta(minutes=10)
    exit_time = datetime.now()
    
    print("\nSimulating trade entry:")
    print(f"  Entry time: {entry_time.isoformat()}")
    print(f"  Exit time:  {exit_time.isoformat()}")
    print(f"  Direction:  PUT")
    print(f"  Entry price (SPY): $450.00")
    print(f"  Exit price (SPY):  $449.50")
    print(f"  Reason:     MAX_HOLD_15_MIN")
    
    # Call log_trade with all fields populated
    log_trade(
        entry_time=entry_time.isoformat(),
        exit_time=exit_time.isoformat(),
        direction="PUT",
        entry_price=450.00,
        exit_price=449.50,
        pnl=0.50,
        exit_reason="MAX_HOLD_15_MIN",
        feature_payload='{"support_resistance": {}, "macd": {}}',
        option_symbol="SPY 07-13-26 P450",
        option_entry=2.50,
        option_exit=3.15,
        option_quantity=1,
        option_delta=-0.65,
        option_return=26.0,
        option_pnl_dollars=65.00,
        option_pnl_pct=26.0,
    )
    
    print("\nOption details:")
    print(f"  Option symbol:    SPY 07-13-26 P450")
    print(f"  Option entry:     $2.50")
    print(f"  Option exit:      $3.15")
    print(f"  Option quantity:  1 contract")
    print(f"  Option delta:     -0.65")
    print(f"  Option return:    26.0%")
    print(f"  Option P/L $:     $65.00")
    print(f"  Option P/L %:     26.0%")
    
    # Read back from database to verify
    print("\n" + "=" * 60)
    print("Verifying data was inserted correctly...")
    print("=" * 60)
    
    with sqlite3.connect("data/mcleod_alpha.db") as con:
        con.row_factory = sqlite3.Row
        cursor = con.cursor()
        
        # Get the most recent trade
        cursor.execute("""
            SELECT * FROM trade_log 
            ORDER BY id DESC 
            LIMIT 1
        """)
        trade = cursor.fetchone()

        assert trade is not None, "No trade found in database"
        
        print("\nRetrieved trade record:")
        print(f"  ID:                  {trade['id']}")
        print(f"  Entry time:          {trade['entry_time']}")
        print(f"  Exit time:           {trade['exit_time']}")
        print(f"  Direction:           {trade['direction']}")
        print(f"  Entry price:         ${trade['entry_price']}")
        print(f"  Exit price:          ${trade['exit_price']}")
        print(f"  P/L:                 ${trade['pnl']}")
        print(f"  Exit reason:         {trade['exit_reason']}")
        
        print("\nOption fields verification:")
        
        required_fields = [
            ('option_symbol', 'SPY 07-13-26 P450'),
            ('option_entry', 2.50),
            ('option_exit', 3.15),
            ('option_quantity', 1),
        ]
        
        all_present = True
        for field_name, expected_value in required_fields:
            value = trade[field_name]
            status = "✓" if value is not None else "✗"
            match = "✓" if value == expected_value else "⚠"
            
            if value is None:
                all_present = False
                print(f"  {status} {field_name:20s} = {value} {match} MISSING")
            else:
                print(f"  {status} {field_name:20s} = {value} {match}")
        
        print("\nExtended option fields:")
        extended_fields = [
            ('option_delta', -0.65),
            ('option_return', 26.0),
            ('option_pnl_dollars', 65.00),
            ('option_pnl_pct', 26.0),
        ]
        
        for field_name, expected_value in extended_fields:
            value = trade[field_name]
            status = "✓" if value is not None else "✗"
            
            if value is None:
                all_present = False
                print(f"  {status} {field_name:20s} = {value} (MISSING)")
            else:
                print(f"  {status} {field_name:20s} = {value}")
        
        if all_present:
            print("\n" + "=" * 60)
            print("✓ SUCCESS: All required option fields are populated!")
            print("=" * 60)
            assert all_present
        else:
            print("\n" + "=" * 60)
            print("✗ FAILURE: Some option fields are missing!")
            print("=" * 60)
            assert all_present, "Some option fields are missing"

if __name__ == "__main__":
    try:
        test_trade_log_fields()
        sys.exit(0)
    except AssertionError:
        sys.exit(1)
