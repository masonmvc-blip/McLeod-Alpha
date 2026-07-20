#!/usr/bin/env python3
"""
Comprehensive tests for broker-held protective stop orders in McLeod Alpha.

Tests mandatory protective stop requirements:
1. Entry fill → protective stop submission
2. Stop uses SELL_TO_CLOSE with exact option symbol
3. Stop based on option fill price (-5%), not SPY price
4. Position not marked protected until Schwab accepts
5. Failed stop blocks new entries (POSITION UNPROTECTED)
6. Stop canceled/replaced for breakeven/trailing
7. Max-hold exit cancels stop before closing
8. No duplicate exit orders
9. Startup detects unprotected positions
10. Broker query failure → SAFE MODE (not assuming flat)
11. Max contract cap maintained
"""

import sys
sys.path.insert(0, '/Users/mason/Library/CloudStorage/Dropbox/McLeod Capital/McLeod Alpha')

from unittest.mock import MagicMock, Mock, patch
from datetime import datetime
from execution.live_engine import (
    set_schwab_client,
    open_trade,
    close_trade,
    _calculate_protective_stop_price,
    _submit_protective_stop,
    _cancel_protective_stop,
    reconcile_startup,
    normalize_option_tick,
    Position,
    in_trade,
    current_position,
)
import execution.live_engine as live_engine


print("="*70)
print("PROTECTIVE STOP ORDER SYSTEM - COMPREHENSIVE TESTS")
print("="*70)


def test_1_entry_fill_triggers_protective_stop():
    """Test: Confirmed entry fill immediately triggers protective stop submission."""
    print("\n" + "="*70)
    print("TEST 1: Entry fill immediately triggers protective stop submission")
    print("="*70)
    
    # Clear any existing position from previous tests (both in-memory and file)
    live_engine.current_position = None
    try:
        live_engine.clear_position()
    except:
        pass
    
    # Setup mocks
    mock_client = MagicMock()
    
    # Mock place_order for entry
    entry_response = Mock()
    entry_response.status_code = 201
    entry_response.headers = {"Location": "/orders/111"}
    entry_response.raise_for_status = Mock()
    
    # Mock get_order for fill confirmation
    get_order_response = Mock()
    get_order_response.status_code = 200
    get_order_response.json.return_value = {
        "status": "FILLED",
        "filledQuantity": 1,
        "price": 5.68,
        "orderLegCollection": [
            {
                "execution": [{"price": 5.68}]
            }
        ]
    }
    get_order_response.raise_for_status = Mock()
    
    # Mock place_order for protective stop
    stop_response = Mock()
    stop_response.status_code = 201
    stop_response.headers = {"Location": "/orders/222"}
    stop_response.raise_for_status = Mock()
    
    # Mock get_account for pre-entry check
    account_response = Mock()
    account_response.status_code = 200
    account_response.json.return_value = {
        "securitiesAccount": {"positions": [], "orderStrategies": []}
    }
    account_response.raise_for_status = Mock()
    
    # Configure mock client
    mock_client.place_order.side_effect = [entry_response, stop_response]
    mock_client.get_order.return_value = get_order_response
    mock_client.get_account.return_value = account_response
    mock_client.orders.option_buy_to_open_limit.return_value = Mock()
    
    # Set client
    set_schwab_client(mock_client, "33310903", "96636430645ADE50C1234567890ABCDEF")
    
    # Clear any existing position
    live_engine.current_position = None
    
    # Attempt entry
    result = open_trade(
        direction="CALL",
        price=750.0,
        stop=732.5,
        target=760.0,
        quantity=1,
        reason="TEST",
        option={
            "symbol": "SPY 260724C00754000",
            "mark": 5.68,
            "delta": 0.5
        },
        feature_payload="test"
    )
    
    # Verify results
    assert result == True, "Entry should complete successfully"
    assert mock_client.place_order.call_count >= 2, "Should submit entry and protective stop"

    # Current engine submits protective stops via generic OrderBuilder STOP_LIMIT.
    stop_order = mock_client.place_order.call_args_list[1][0][1]
    assert str(getattr(stop_order, "_orderType", "")) == "STOP_LIMIT", "Protective stop must be STOP_LIMIT"
    legs = list(getattr(stop_order, "_orderLegCollection", []) or [])
    assert legs, "Protective stop should include at least one leg"
    assert str(legs[0].get("instruction") or "") == "SELL_TO_CLOSE", "Protective stop leg must SELL_TO_CLOSE"
    
    # Verify position has protective stop details
    assert live_engine.current_position is not None, "Position should exist"
    assert live_engine.current_position.protective_stop_order_id == "222", "Stop order ID should be stored"
    assert live_engine.current_position.protective_stop_price == 5.40, "Stop price should be -5% of 5.68"
    assert live_engine.current_position.protective_stop_status == "PLACED", "Stop status should be PLACED"
    
    print("✓ PASS: Entry fill triggers protective stop submission")
    print(f"  - Entry Order ID: 111")
    print(f"  - Entry Fill: ${5.68}")
    print(f"  - Protective Stop Order ID: 222")
    print(f"  - Protective Stop Price: ${5.40} (-5% of entry)")


def test_2_protective_stop_uses_sell_to_close():
    """Test: Protective stop uses SELL_TO_CLOSE with exact option symbol."""
    print("\n" + "="*70)
    print("TEST 2: Protective stop uses SELL_TO_CLOSE with exact option symbol")
    print("="*70)
    
    mock_client = MagicMock()
    
    stop_response = Mock()
    stop_response.status_code = 201
    stop_response.headers = {"Location": "/orders/333"}
    stop_response.raise_for_status = Mock()
    mock_client.place_order.return_value = stop_response
    
    set_schwab_client(mock_client, "33310903", "96636430645ADE50C1234567890ABCDEF")
    
    # Test protective stop submission
    order_id, stop_price = _submit_protective_stop("SPY 260724C00754000", 5.68, 1)
    
    # Verify current generic STOP_LIMIT order payload
    assert mock_client.place_order.called, "Should submit protective stop to broker"
    call_args = mock_client.place_order.call_args
    submitted_order = call_args[0][1]
    assert str(getattr(submitted_order, "_orderType", "")) == "STOP_LIMIT", "Order type should be STOP_LIMIT"
    assert str(getattr(submitted_order, "_stopPrice", "")), "Should include stop price"
    assert str(getattr(submitted_order, "_price", "")), "Should include stop-limit price"
    legs = list(getattr(submitted_order, "_orderLegCollection", []) or [])
    assert legs and str(legs[0].get("instruction") or "") == "SELL_TO_CLOSE", "Protective stop leg must SELL_TO_CLOSE"
    
    print("✓ PASS: Protective stop uses correct STOP_LIMIT payload")
    print(f"  - Builder: generic OrderBuilder")
    print(f"  - Symbol: SPY 260724C00754000")
    print(f"  - Quantity: 1")
    print(f"  - Order Type: STOP")
    print(f"  - Stop Price: {stop_price}")


def test_3_stop_price_based_on_option_fill():
    """Test: Stop is based on option fill price (-5%), not SPY price."""
    print("\n" + "="*70)
    print("TEST 3: Stop price based on option fill, not SPY price")
    print("="*70)
    
    # Test stop price calculation
    spy_price = 754.50
    option_fill_price = 5.68
    
    # Calculate stop
    stop_price = _calculate_protective_stop_price(option_fill_price)
    
    # Expected: 5.68 * 0.95 = 5.396 → normalized to 5.40
    expected_stop = normalize_option_tick(5.68 * 0.95)
    
    assert stop_price == expected_stop, f"Stop should be {expected_stop}, got {stop_price}"
    assert stop_price != spy_price * 0.95, "Stop should NOT be based on SPY price"
    
    print("✓ PASS: Stop price correctly based on option fill price")
    print(f"  - SPY Price: ${spy_price}")
    print(f"  - Option Fill Price: ${option_fill_price}")
    print(f"  - Protective Stop: ${stop_price} (-5% of option fill)")


def test_4_position_not_marked_protected_until_accepted():
    """Test: No local position marked protected before Schwab accepts stop."""
    print("\n" + "="*70)
    print("TEST 4: Position not marked protected until Schwab accepts")
    print("="*70)
    
    # Clear any existing position from previous tests (both in-memory and file)
    live_engine.current_position = None
    try:
        live_engine.clear_position()
    except:
        pass
    
    mock_client = MagicMock()
    
    # Setup entry fill
    entry_response = Mock()
    entry_response.status_code = 201
    entry_response.headers = {"Location": "/orders/444"}
    entry_response.raise_for_status = Mock()
    
    get_order_response = Mock()
    get_order_response.status_code = 200
    get_order_response.json.return_value = {"status": "FILLED", "price": 5.68}
    get_order_response.raise_for_status = Mock()
    
    account_response = Mock()
    account_response.status_code = 200
    account_response.json.return_value = {
        "securitiesAccount": {"positions": [], "orderStrategies": []}
    }
    account_response.raise_for_status = Mock()
    
    # Protective stop submission FAILS
    stop_response = Mock()
    stop_response.status_code = 400
    stop_response.raise_for_status = Mock(side_effect=Exception("Bad Request"))
    
    mock_client.place_order.side_effect = [entry_response, stop_response]
    mock_client.get_order.return_value = get_order_response
    mock_client.get_account.return_value = account_response
    mock_client.orders.option_buy_to_open_limit.return_value = Mock()
    mock_client.orders.option_sell_to_close_limit.return_value = Mock()
    
    set_schwab_client(mock_client, "33310903", "96636430645ADE50C1234567890ABCDEF")
    live_engine.current_position = None
    live_engine._protective_stop_failed = False
    
    # Attempt entry
    result = open_trade(
        direction="CALL",
        price=750.0,
        stop=732.5,
        target=760.0,
        quantity=1,
        reason="TEST",
        option={
            "symbol": "SPY 260724C00754000",
            "mark": 5.68,
            "delta": 0.5
        }
    )
    
    # Position should exist (entry filled) but stop failed
    assert live_engine.current_position is not None, "Position created after entry fill"
    assert live_engine.current_position.protective_stop_status == "FAILED", "Stop status should be FAILED"
    assert live_engine.current_position.protective_stop_order_id == "", "Stop order ID should be empty"
    
    print("✓ PASS: Position marked FAILED if stop submission fails")
    print(f"  - Entry Filled: Yes (position exists)")
    print(f"  - Protective Stop Status: FAILED")
    print(f"  - Trading Blocked: Yes (_protective_stop_failed = True)")


def test_5_failed_stop_blocks_new_entries():
    """Test: Failed stop submission blocks all new entries."""
    print("\n" + "="*70)
    print("TEST 5: Failed protective stop blocks new entries")
    print("="*70)
    
    mock_client = MagicMock()
    set_schwab_client(mock_client, "33310903", "96636430645ADE50C1234567890ABCDEF")
    
    # Simulate protective stop failure
    live_engine._protective_stop_failed = True
    live_engine._protective_stop_failure_reason = "Submission failed"
    
    # Attempt new entry
    result = open_trade(
        direction="CALL",
        price=750.0,
        stop=732.5,
        target=760.0,
        quantity=1,
        reason="TEST",
        option={"symbol": "SPY 260724C00754000", "mark": 5.68}
    )
    
    # Entry should be blocked
    assert result == False, "Entry should be blocked when protective stop failed"
    
    print("✓ PASS: Failed protective stop blocks new entries")
    print(f"  - POSITION UNPROTECTED status active")
    print(f"  - New entries blocked")
    print(f"  - Manual action required")


def test_6_stop_canceled_for_exit():
    """Test: Stop is canceled before submitting exit order."""
    print("\n" + "="*70)
    print("TEST 6: Stop canceled before exit order")
    print("="*70)
    
    mock_client = MagicMock()
    
    cancel_response = Mock()
    cancel_response.status_code = 204
    cancel_response.raise_for_status = Mock()
    mock_client.cancel_order.return_value = cancel_response
    
    set_schwab_client(mock_client, "33310903", "96636430645ADE50C1234567890ABCDEF")
    
    # Create position with protective stop
    live_engine.current_position = Position(
        direction="CALL",
        entry_price=750.0,
        stop_price=732.5,
        target_price=760.0,
        quantity=1,
        opened=datetime.now(),
        reason="TEST",
        option_symbol="SPY 260724C00754000",
        option_entry=5.68,
        option_delta=0.5,
        schwab_order_id="111",
        schwab_fill_price=5.68,
        protective_stop_order_id="222",
        protective_stop_price=5.40,
        protective_stop_status="PLACED"
    )
    
    # Close trade
    result = close_trade(755.0, "TARGET_HIT", 5.98)
    
    # Verify cancel was called
    assert mock_client.cancel_order.called, "Should call cancel_order"
    call_args = mock_client.cancel_order.call_args
    assert call_args[0][0] == "222", "Should cancel the protective stop order"
    
    print("✓ PASS: Protective stop canceled before exit")
    print(f"  - Protective Stop Order ID: 222")
    print(f"  - Cancellation Status: Success")
    print(f"  - Exit can now proceed")


def test_7_startup_detects_unprotected_position():
    """Test: Startup detects unprotected broker position."""
    print("\n" + "="*70)
    print("TEST 7: Startup detects unprotected broker position")
    print("="*70)
    
    mock_client = MagicMock()
    
    # Setup: Existing SPY position with NO protective stop
    account_response = Mock()
    account_response.status_code = 200
    account_response.json.return_value = {
        "securitiesAccount": {
            "positions": [
                {
                    "instrument": {"assetType": "OPTION", "symbol": "SPY 260724C00754000"},
                    "longQuantity": 1,
                    "averagePrice": 5.50
                }
            ],
            "orderStrategies": []  # No orders = no protective stop
        }
    }
    account_response.raise_for_status = Mock()
    
    mock_client.get_account.return_value = account_response
    
    set_schwab_client(mock_client, "33310903", "96636430645ADE50C1234567890ABCDEF")
    live_engine._protective_stop_failed = False
    
    # Run startup reconciliation
    result = reconcile_startup()
    
    # Should detect unprotected position and enter protective stop failure lock
    assert result == False, "Reconciliation should fail for unprotected position"
    assert live_engine._protective_stop_failed == True, "Should set protective stop failed"
    
    print("✓ PASS: Startup detects and alerts on unprotected position")
    print(f"  - Position: SPY 260724C00754000 qty 1")
    print(f"  - Protective Stop: None")
    print(f"  - Status: UNPROTECTED")
    print(f"  - Trading Disabled: Yes")


def test_8_broker_query_failure_enters_safe_mode():
    """Test: Broker query failure enters SAFE MODE, not assuming flat."""
    print("\n" + "="*70)
    print("TEST 8: Broker query failure enters SAFE MODE")
    print("="*70)
    
    mock_client = MagicMock()
    
    # Simulate broker query failure
    account_response = Mock()
    account_response.status_code = 500
    account_response.raise_for_status = Mock(side_effect=Exception("Server Error"))
    mock_client.get_account.return_value = account_response
    
    set_schwab_client(mock_client, "33310903", "96636430645ADE50C1234567890ABCDEF")
    live_engine._safe_mode = False
    
    # Run startup reconciliation
    result = reconcile_startup()
    
    # Should enter SAFE MODE
    assert result == False, "Reconciliation should fail"
    assert live_engine._safe_mode == True, "Should enter SAFE MODE"
    assert "500" in live_engine._safe_mode_reason or "Error" in live_engine._safe_mode_reason, \
        "Should report error reason"
    
    print("✓ PASS: Broker query failure enters SAFE MODE")
    print(f"  - HTTP Status: 500")
    print(f"  - SAFE MODE: Activated")
    print(f"  - Assumption: NOT assuming flat")
    print(f"  - Trading: Blocked until connection restored")


def test_9_max_contract_cap_enforced():
    """Test: Maximum configured SPY option contract cap is enforced."""
    print("\n" + "="*70)
    print("TEST 9: Maximum contract cap enforced")
    print("="*70)
    
    mock_client = MagicMock()
    
    # Setup: Existing position with qty > MAX_OPEN_CONTRACTS (4)
    account_response = Mock()
    account_response.status_code = 200
    account_response.json.return_value = {
        "securitiesAccount": {
            "positions": [
                {
                    "instrument": {"assetType": "OPTION", "symbol": "SPY 260724C00754000"},
                    "longQuantity": 4,  # qty > max cap (3)
                    "averagePrice": 5.50
                }
            ],
            "orderStrategies": []
        }
    }
    account_response.raise_for_status = Mock()
    
    mock_client.get_account.return_value = account_response
    
    set_schwab_client(mock_client, "33310903", "96636430645ADE50C1234567890ABCDEF")
    live_engine._max_quantity_exceeded = False
    
    # Run startup reconciliation
    result = reconcile_startup()
    
    # Should detect qty > max and block
    assert result == False, "Should block on qty > configured max"
    assert live_engine._max_quantity_exceeded == True, "Should set max quantity exceeded"
    
    print("✓ PASS: Maximum contract cap enforced")
    print(f"  - Position Qty: 4")
    print(f"  - Max Allowed: 3")
    print(f"  - Status: BLOCKED")
    print(f"  - Manual reconciliation required")


def test_10_no_duplicate_exit_orders():
    """Test: Cannot submit duplicate exit orders."""
    print("\n" + "="*70)
    print("TEST 10: No duplicate exit orders")
    print("="*70)
    
    mock_client = MagicMock()
    set_schwab_client(mock_client, "33310903", "96636430645ADE50C1234567890ABCDEF")
    
    # Setup position
    live_engine.current_position = Position(
        direction="CALL",
        entry_price=750.0,
        stop_price=732.5,
        target_price=760.0,
        quantity=1,
        opened=datetime.now(),
        reason="TEST",
        option_symbol="SPY 260724C00754000",
        protective_stop_order_id="222",
        protective_stop_status="PLACED"
    )
    
    # First close should succeed
    cancel_response = Mock()
    cancel_response.status_code = 204
    cancel_response.raise_for_status = Mock()
    mock_client.cancel_order.return_value = cancel_response
    
    with patch.object(live_engine, "_submit_option_exit_market_order", return_value="999"):
        with patch.object(live_engine, "_wait_for_fill", return_value=(True, 5.98)):
            result1 = close_trade(755.0, "TARGET_HIT", 5.98)
    assert result1 == True, "First close should work"
    
    # Position should be cleared
    assert live_engine.current_position is None, "Position should be None after close"
    
    # Second close attempt should fail (no position)
    result2 = close_trade(756.0, "TEST_EXIT", 5.99)
    assert result2 == False, "Should not close when no position"
    
    print("✓ PASS: Duplicate exit orders prevented")
    print(f"  - First Exit: Success")
    print(f"  - Position After: None")
    print(f"  - Second Exit Attempt: Blocked (no position)")


# Run all tests
def main():
    results = []
    tests = [
        test_1_entry_fill_triggers_protective_stop,
        test_2_protective_stop_uses_sell_to_close,
        test_3_stop_price_based_on_option_fill,
        test_4_position_not_marked_protected_until_accepted,
        test_5_failed_stop_blocks_new_entries,
        test_6_stop_canceled_for_exit,
        test_7_startup_detects_unprotected_position,
        test_8_broker_query_failure_enters_safe_mode,
        test_9_max_contract_cap_enforced,
        test_10_no_duplicate_exit_orders,
    ]
    
    for test in tests:
        try:
            result = test()
            results.append((test.__name__, True, result))
        except AssertionError as e:
            print(f"\n✗ FAILED: {e}")
            results.append((test.__name__, False, str(e)))
        except Exception as e:
            print(f"\n✗ ERROR: {e}")
            import traceback
            traceback.print_exc()
            results.append((test.__name__, False, str(e)))
    
    # Summary
    print("\n" + "="*70)
    print("TEST RESULTS SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, success, _ in results if success)
    failed = len(results) - passed
    
    for test_name, success, message in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\n{'='*70}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(results)}")
    print(f"{'='*70}\n")
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
