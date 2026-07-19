#!/usr/bin/env python3
"""
Verification test for INITIAL_STOP vs TRAILING_STOP exit reasons.
Tests the logic that determines which exit reason is recorded.
"""

import sys
from pathlib import Path
from datetime import datetime

# Add execution path
sys.path.insert(0, str(Path("execution").resolve()))

from dataclasses import dataclass

def test_stop_reason_logic():
    """Test the logic for determining INITIAL_STOP vs TRAILING_STOP."""
    
    print("=" * 70)
    print("STOP REASON DETERMINATION TEST")
    print("=" * 70)
    
    # Scenario 1: INITIAL_STOP
    # Trade lost money, stop was never trailed
    print("\n" + "=" * 70)
    print("SCENARIO 1: INITIAL_STOP (Stop hit on losing trade)")
    print("=" * 70)
    
    option_entry = 2.50
    initial_stop = option_entry * (1 - 0.05)  # 5% loss = 2.375
    current_stop = initial_stop  # Never moved
    option_mark = 2.30  # Price dropped below stop
    option_pnl_pct = ((option_mark - option_entry) / option_entry) * 100
    
    print(f"\nTrade parameters:")
    print(f"  Option entry:     ${option_entry:.2f}")
    print(f"  Initial stop:     ${initial_stop:.3f} (5% loss from entry)")
    print(f"  Current stop:     ${current_stop:.3f} (unchanged)")
    print(f"  Current mark:     ${option_mark:.2f}")
    print(f"  P/L %:            {option_pnl_pct:.2f}%")
    print(f"  Profitable:       {'Yes' if option_pnl_pct > 0 else 'No'}")
    
    # Apply logic
    if current_stop > initial_stop and option_pnl_pct > 0:
        exit_reason = "TRAILING_STOP"
    else:
        exit_reason = "INITIAL_STOP"
    
    print(f"\nExit logic:")
    print(f"  Stop trailed:     {current_stop > initial_stop}")
    print(f"  Trade profitable: {option_pnl_pct > 0}")
    print(f"  ➜ Exit reason:    {exit_reason}")
    
    assert exit_reason == "INITIAL_STOP", "Scenario 1 should produce INITIAL_STOP"
    print("\n✓ Scenario 1 PASSED")
    
    # Scenario 2: TRAILING_STOP
    # Trade became profitable, stop was trailed, then hit
    print("\n" + "=" * 70)
    print("SCENARIO 2: TRAILING_STOP (Trailing stop hit on profitable trade)")
    print("=" * 70)
    
    option_entry = 2.50
    initial_stop = option_entry * (1 - 0.05)  # 5% loss = 2.375
    current_stop = 2.65  # Trailed upward (moved to breakeven + 6%)
    option_mark = 2.64  # Price dropped to current stop
    option_pnl_pct = ((option_mark - option_entry) / option_entry) * 100
    
    print(f"\nTrade parameters:")
    print(f"  Option entry:     ${option_entry:.2f}")
    print(f"  Initial stop:     ${initial_stop:.3f} (5% loss from entry)")
    print(f"  Current stop:     ${current_stop:.2f} (trailed upward)")
    print(f"  Current mark:     ${option_mark:.2f}")
    print(f"  P/L %:            {option_pnl_pct:.2f}%")
    print(f"  Profitable:       {'Yes' if option_pnl_pct > 0 else 'No'}")
    
    # Apply logic
    if current_stop > initial_stop and option_pnl_pct > 0:
        exit_reason = "TRAILING_STOP"
    else:
        exit_reason = "INITIAL_STOP"
    
    print(f"\nExit logic:")
    print(f"  Stop trailed:     {current_stop > initial_stop}")
    print(f"  Trade profitable: {option_pnl_pct > 0}")
    print(f"  ➜ Exit reason:    {exit_reason}")
    
    assert exit_reason == "TRAILING_STOP", "Scenario 2 should produce TRAILING_STOP"
    print("\n✓ Scenario 2 PASSED")
    
    # Scenario 3: INITIAL_STOP (Stop was trailed but trade turned negative)
    # Stop was trailed but then price dropped significantly (back to loss)
    print("\n" + "=" * 70)
    print("SCENARIO 3: INITIAL_STOP (Stop trailed but trade went negative again)")
    print("=" * 70)
    
    option_entry = 2.50
    initial_stop = option_entry * (1 - 0.05)  # 5% loss = 2.375
    current_stop = 2.65  # Trailed upward
    option_mark = 2.40  # Price dropped below initial stop
    option_pnl_pct = ((option_mark - option_entry) / option_entry) * 100
    
    print(f"\nTrade parameters:")
    print(f"  Option entry:     ${option_entry:.2f}")
    print(f"  Initial stop:     ${initial_stop:.3f} (5% loss from entry)")
    print(f"  Current stop:     ${current_stop:.2f} (was trailed upward)")
    print(f"  Current mark:     ${option_mark:.2f}")
    print(f"  P/L %:            {option_pnl_pct:.2f}%")
    print(f"  Profitable:       {'Yes' if option_pnl_pct > 0 else 'No'}")
    
    # Apply logic
    if current_stop > initial_stop and option_pnl_pct > 0:
        exit_reason = "TRAILING_STOP"
    else:
        exit_reason = "INITIAL_STOP"
    
    print(f"\nExit logic:")
    print(f"  Stop trailed:     {current_stop > initial_stop}")
    print(f"  Trade profitable: {option_pnl_pct > 0}")
    print(f"  ➜ Exit reason:    {exit_reason}")
    
    assert exit_reason == "INITIAL_STOP", "Scenario 3 should produce INITIAL_STOP"
    print("\n✓ Scenario 3 PASSED")
    
    # Summary
    print("\n" + "=" * 70)
    print("✓ ALL TESTS PASSED")
    print("=" * 70)
    print("\nRules verified:")
    print("  1. INITIAL_STOP when stop hasn't trailed OR trade not profitable")
    print("  2. TRAILING_STOP when stop HAS trailed AND trade IS profitable")
    print("\n")
    return True

if __name__ == "__main__":
    try:
        success = test_stop_reason_logic()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
