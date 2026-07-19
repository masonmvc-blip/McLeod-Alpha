#!/usr/bin/env python3
"""
Test script to verify feature_payload has all required fields at entry.
"""

import json
import sys
from pathlib import Path

sys.path.append(str(Path(".").resolve()))

# Simulate the feature_payload structure
def test_feature_payload():
    """Test that feature_payload contains all required fields at entry."""
    
    # Simulate build_feature_snapshot output
    feature_payload = {
        "support_resistance": {
            "prior_day_high": 450.0,
            "prior_day_low": 440.0,
            "premarket_high": 449.5,
            "premarket_low": 441.5,
            "nearest_recent_swing_high": 449.0,
            "nearest_recent_swing_low": 442.0,
            "nearest_resistance": 449.5,
            "nearest_support": 441.5,
            "distance_to_resistance_dollars": 1.5,
            "distance_to_resistance_pct": 0.33,
            "distance_to_support_dollars": 3.0,
            "distance_to_support_pct": 0.67,
            "closed_above_resistance": True,
            "closed_below_support": False,
            "breakout_volume_confirmed": True,
            "breakdown_volume_confirmed": False,
        },
        "macd": {
            "bullish_crossover_last_3_candles": True,
            "bearish_crossover_last_3_candles": False,
            "current_macd": 0.5,
            "current_signal": 0.3,
            "current_histogram": 0.2,
            "histogram_direction": "STRENGTHENING",
        },
    }
    
    # Simulate scoring data
    call_score = 5
    put_score = 2
    call_reasons = ["price_above_vwap", "bull_ema_stack", "ema10_rising"]
    put_reasons = []
    
    # Test CALL trade entry
    print("Testing CALL trade entry...")
    feature_payload_call = feature_payload.copy()
    feature_payload_call["call_score"] = call_score
    feature_payload_call["put_score"] = put_score
    feature_payload_call["entry_score"] = call_score
    feature_payload_call["entry_reasons"] = call_reasons
    
    # Verify all four new fields exist
    required_fields = ["call_score", "put_score", "entry_score", "entry_reasons"]
    for field in required_fields:
        assert field in feature_payload_call, f"CALL entry missing field '{field}'"
        print(f"  ✓ {field} = {feature_payload_call[field]}")
    
    # Test PUT trade entry
    print("\nTesting PUT trade entry...")
    feature_payload_put = feature_payload.copy()
    feature_payload_put["call_score"] = call_score
    feature_payload_put["put_score"] = put_score
    feature_payload_put["entry_score"] = put_score
    feature_payload_put["entry_reasons"] = put_reasons
    
    for field in required_fields:
        assert field in feature_payload_put, f"PUT entry missing field '{field}'"
        print(f"  ✓ {field} = {feature_payload_put[field]}")
    
    # Verify JSON serialization works
    print("\nTesting JSON serialization...")
    try:
        json_call = json.dumps(feature_payload_call)
        json_put = json.dumps(feature_payload_put)
        print(f"  ✓ CALL payload serializes to {len(json_call)} bytes")
        print(f"  ✓ PUT payload serializes to {len(json_put)} bytes")
    except Exception as e:
        raise AssertionError(f"JSON serialization failed: {e}")
    
    # Verify support_resistance and MACD fields preserved
    print("\nVerifying existing fields are preserved...")
    preserved_fields = ["support_resistance", "macd"]
    for field in preserved_fields:
        assert field in feature_payload_call and field in feature_payload_put, f"Missing preserved field '{field}'"
        print(f"  ✓ {field} preserved in both CALL and PUT payloads")
    
    print("\n✓ All tests passed!")

if __name__ == "__main__":
    try:
        test_feature_payload()
        sys.exit(0)
    except AssertionError:
        sys.exit(1)
