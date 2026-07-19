#!/usr/bin/env python3
"""
Regression tests for Schwab order reconciliation fix.

Tests that terminal order statuses (FILLED, CANCELED, REPLACED, EXPIRED, REJECTED)
do not block trading, and only active statuses can block.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import MagicMock, patch
import execution.live_engine as le


def create_mock_order(
    order_id, 
    symbol, 
    instruction, 
    quantity, 
    status, 
    asset_type="OPTION"
):
    """Helper to create a mock order"""
    return {
        "orderId": order_id,
        "status": status,
        "orderLegCollection": [
            {
                "quantity": quantity,
                "instruction": instruction,
                "instrument": {
                    "symbol": symbol,
                    "assetType": asset_type,
                }
            }
        ]
    }


def test_replaced_order_does_not_block():
    """REPLACED orders should not block trading"""
    print("\n✓ Test: REPLACED orders do not block trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],  # positions
            [create_mock_order("123", "SPY   260724C00754000", "BUY", 3, "REPLACED")],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert not has_exposure, "REPLACED order should not block"
        assert details is None
        print("  ✓ REPLACED order correctly does not block")


def test_canceled_order_does_not_block():
    """CANCELED orders should not block trading"""
    print("\n✓ Test: CANCELED orders do not block trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],
            [create_mock_order("124", "SPY   260724C00754000", "BUY", 3, "CANCELED")],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert not has_exposure, "CANCELED order should not block"
        assert details is None
        print("  ✓ CANCELED order correctly does not block")


def test_filled_order_does_not_block():
    """FILLED orders should not block trading"""
    print("\n✓ Test: FILLED orders do not block trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],
            [create_mock_order("125", "SPY   260724C00754000", "BUY", 3, "FILLED")],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert not has_exposure, "FILLED order should not block"
        assert details is None
        print("  ✓ FILLED order correctly does not block")


def test_expired_order_does_not_block():
    """EXPIRED orders should not block trading"""
    print("\n✓ Test: EXPIRED orders do not block trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],
            [create_mock_order("126", "SPY   260724C00754000", "BUY", 3, "EXPIRED")],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert not has_exposure, "EXPIRED order should not block"
        assert details is None
        print("  ✓ EXPIRED order correctly does not block")


def test_rejected_order_does_not_block():
    """REJECTED orders should not block trading"""
    print("\n✓ Test: REJECTED orders do not block trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],
            [create_mock_order("127", "SPY   260724C00754000", "BUY", 3, "REJECTED")],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert not has_exposure, "REJECTED order should not block"
        assert details is None
        print("  ✓ REJECTED order correctly does not block")


def test_working_order_blocks():
    """WORKING orders should block trading"""
    print("\n✓ Test: WORKING orders block trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],
            [create_mock_order("128", "SPY   260724C00754000", "BUY", 3, "WORKING")],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert has_exposure, "WORKING order should block"
        assert "WORKING" in details
        print("  ✓ WORKING order correctly blocks")


def test_pending_activation_order_blocks():
    """PENDING_ACTIVATION orders should block trading"""
    print("\n✓ Test: PENDING_ACTIVATION orders block trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],
            [create_mock_order("129", "SPY   260724P00754000", "BUY", 2, "PENDING_ACTIVATION")],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert has_exposure, "PENDING_ACTIVATION order should block"
        assert "PENDING_ACTIVATION" in details
        print("  ✓ PENDING_ACTIVATION order correctly blocks")


def test_queued_order_blocks():
    """QUEUED orders should block trading"""
    print("\n✓ Test: QUEUED orders block trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],
            [create_mock_order("130", "SPY   260724C00754000", "BUY", 3, "QUEUED")],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert has_exposure, "QUEUED order should block"
        assert "QUEUED" in details
        print("  ✓ QUEUED order correctly blocks")


def test_accepted_order_blocks():
    """ACCEPTED orders should block trading"""
    print("\n✓ Test: ACCEPTED orders block trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],
            [create_mock_order("131", "SPY   260724P00754000", "BUY", 2, "ACCEPTED")],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert has_exposure, "ACCEPTED order should block"
        assert "ACCEPTED" in details
        print("  ✓ ACCEPTED order correctly blocks")


def test_partially_filled_order_blocks():
    """PARTIALLY_FILLED orders should block trading"""
    print("\n✓ Test: PARTIALLY_FILLED orders block trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],
            [create_mock_order("132", "SPY   260724C00754000", "BUY", 3, "PARTIALLY_FILLED")],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert has_exposure, "PARTIALLY_FILLED order should block"
        assert "PARTIALLY_FILLED" in details
        print("  ✓ PARTIALLY_FILLED order correctly blocks")


def test_multiple_replaced_orders_dont_block():
    """Multiple REPLACED orders should not block trading"""
    print("\n✓ Test: Multiple REPLACED orders do not block trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],
            [
                create_mock_order("133", "SPY   260724C00754000", "BUY", 3, "REPLACED"),
                create_mock_order("134", "SPY   260710C00750000", "BUY", 3, "REPLACED"),
                create_mock_order("135", "SPY   260710C00748000", "BUY", 10, "REPLACED"),
            ],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert not has_exposure, "Multiple REPLACED orders should not block"
        assert details is None
        print("  ✓ Multiple REPLACED orders correctly do not block")


def test_mixed_terminal_and_active_only_active_blocks():
    """Mix of terminal and active orders - only active should block"""
    print("\n✓ Test: Mix of terminal and active orders - only active blocks")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],
            [
                create_mock_order("136", "SPY   260724C00754000", "BUY", 3, "REPLACED"),
                create_mock_order("137", "SPY   260710C00750000", "BUY", 3, "FILLED"),
                create_mock_order("138", "SPY   260710C00748000", "BUY", 10, "WORKING"),  # This one blocks
                create_mock_order("139", "SPY   260710C00745000", "BUY", 3, "CANCELED"),
            ],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert has_exposure, "Should block due to WORKING order"
        assert "WORKING" in details
        print("  ✓ Mix correctly blocks on active order only")


def test_open_position_blocks_regardless_of_orders():
    """An open SPY position should block regardless of order statuses"""
    print("\n✓ Test: Open position blocks regardless of orders")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [
                {
                    "instrument": {"assetType": "OPTION", "symbol": "SPY   260724C00754000"},
                    "longQuantity": 1,  # Open position
                }
            ],
            [
                create_mock_order("140", "SPY   260724C00754000", "BUY", 3, "REPLACED"),
            ],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert has_exposure, "Should block due to open position"
        assert "Position" in details
        print("  ✓ Open position correctly blocks")


def test_no_position_no_active_orders_allows_trading():
    """No position + only terminal orders = allows trading"""
    print("\n✓ Test: No position + terminal orders = allows trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],  # No positions
            [
                create_mock_order("141", "SPY   260724C00754000", "BUY", 3, "REPLACED"),
                create_mock_order("142", "SPY   260710C00750000", "BUY", 3, "FILLED"),
                create_mock_order("143", "SPY   260710C00748000", "BUY", 10, "CANCELED"),
                create_mock_order("144", "SPY   260710C00745000", "BUY", 3, "EXPIRED"),
            ],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert not has_exposure, "Should allow trading (no active exposure)"
        assert details is None
        print("  ✓ No position + terminal orders correctly allows trading")


def test_empty_broker_state_allows_trading():
    """Empty broker state = allows trading"""
    print("\n✓ Test: Empty broker state allows trading")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],  # No positions
            [],  # No orders
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert not has_exposure, "Should allow trading (clean broker state)"
        assert details is None
        print("  ✓ Empty broker state correctly allows trading")


def test_non_spy_options_ignored():
    """Non-SPY options should be ignored"""
    print("\n✓ Test: Non-SPY options ignored")
    
    with patch.object(le, 'get_schwab_positions') as mock_get:
        mock_get.return_value = (
            [],
            [
                create_mock_order("145", "QQQ   260724C00754000", "BUY", 3, "WORKING"),  # QQQ, not SPY
                create_mock_order("146", "IWM   260724C00754000", "BUY", 3, "WORKING"),  # IWM, not SPY
            ],
            200,
            None
        )
        
        has_exposure, details = le.check_spy_option_exposure()
        assert not has_exposure, "Non-SPY options should not block"
        assert details is None
        print("  ✓ Non-SPY options correctly ignored")


def run_all_tests():
    """Run all regression tests"""
    print("\n" + "="*80)
    print("SCHWAB ORDER RECONCILIATION REGRESSION TESTS")
    print("="*80)
    
    tests = [
        test_replaced_order_does_not_block,
        test_canceled_order_does_not_block,
        test_filled_order_does_not_block,
        test_expired_order_does_not_block,
        test_rejected_order_does_not_block,
        test_working_order_blocks,
        test_pending_activation_order_blocks,
        test_queued_order_blocks,
        test_accepted_order_blocks,
        test_partially_filled_order_blocks,
        test_multiple_replaced_orders_dont_block,
        test_mixed_terminal_and_active_only_active_blocks,
        test_open_position_blocks_regardless_of_orders,
        test_no_position_no_active_orders_allows_trading,
        test_empty_broker_state_allows_trading,
        test_non_spy_options_ignored,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  ✗ FAILED: {str(e)}")
    
    print("\n" + "="*80)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*80 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
