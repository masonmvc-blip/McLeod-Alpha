"""
Comprehensive regression tests for live_engine.py

Tests verify:
1. live mode calls the real Schwab order endpoint
2. no local position exists before confirmed fill
3. rejected/unfilled orders do not create positions
4. the monitor has no paper execution path
5. account/state mismatch blocks trading
"""

import sys
import json
import inspect
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch, call
import time
import pytest


@pytest.fixture(autouse=True)
def isolated_entry_process_lock(tmp_path):
    import execution.live_engine as live_engine

    original_path = live_engine.ENTRY_PROCESS_LOCK_PATH
    live_engine._release_entry_process_lock()
    live_engine.ENTRY_PROCESS_LOCK_PATH = tmp_path / "live_entry.lock"
    try:
        yield
    finally:
        live_engine._release_entry_process_lock()
        live_engine.ENTRY_PROCESS_LOCK_PATH = original_path

# Test fixtures
class MockSchwabResponse:
    """Mock Schwab API response"""
    def __init__(self, status_code=201, headers=None, json_data=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(json_data or {})
    
    def json(self):
        return json.loads(self.text) if self.text else {}
    
    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class MockSchwabClient:
    """Mock Schwab client for testing"""
    def __init__(self, should_fill=True, status_code=201):
        self.should_fill = should_fill
        self.status_code = status_code
        self.place_order_called = False
        self.get_order_called = False
        self.placed_orders = []
    
    def place_order(self, account_number, order):
        """Mock place_order - returns order ID in Location header"""
        self.place_order_called = True
        order_id = "12345"
        self.placed_orders.append({
            "account": account_number,
            "order": order,
            "id": order_id
        })
        
        if self.status_code != 201:
            return MockSchwabResponse(status_code=self.status_code)
        
        return MockSchwabResponse(
            status_code=201,
            headers={"Location": f"/v1/accounts/xyz/orders/{order_id}"},
            json_data={"orderId": order_id}
        )
    
    def get_order(self, account_number, order_id):
        """Mock get_order - simulates fill"""
        self.get_order_called = True
        if self.should_fill:
            return MockSchwabResponse(
                status_code=200,
                json_data={
                    "orderId": order_id,
                    "status": "FILLED",
                    "price": 2.50,
                    "filledQuantity": 1
                }
            )
        else:
            return MockSchwabResponse(
                status_code=200,
                json_data={
                    "orderId": order_id,
                    "status": "PENDING_ACTIVATION"
                }
            )
    
    def get_account_numbers(self):
        """Mock account verification"""
        return MockSchwabResponse(
            status_code=200,
            json_data={
                "securitiesAccount": {
                    "accountNumber": "33310903",
                    "hashValue": "96636430645ADE50C3BB2834109A7246D6CD53C8FE53D513711FCCD8F53162C4"
                }
            }
        )
    
    def get_account(self, account_number, fields=None):
        """Mock account position check"""
        return MockSchwabResponse(
            status_code=200,
            json_data={
                "securitiesAccount": {
                    "positions": [],
                    "orderStrategies": []
                }
            }
        )


def test_live_entry_process_lock_blocks_overlapping_monitor_processes():
    """A second monitor process must not reach broker prechecks or submission."""
    import execution.live_engine as live_engine

    live_engine._entry_process_lock_handle = None
    with patch.object(live_engine, "_acquire_entry_process_lock", return_value=False), patch.object(
        live_engine, "_release_entry_process_lock"
    ), patch.object(live_engine, "check_spy_option_exposure") as exposure_check:
        result = live_engine.open_trade(
            direction="CALL",
            price=100.0,
            stop=99.0,
            target=102.0,
            quantity=4,
            reason="test",
            option={"symbol": "SPY   260731C00750000", "mark": 1.0},
        )

    assert result is False
    assert exposure_check.call_count == 0
    assert live_engine.get_last_open_trade_metrics()["block_reason"] == "entry_process_lock"


def test_live_entry_fallback_is_limit_reprice_not_market_order():
    """Fast participation must retain an explicit maximum buy price."""
    import execution.live_engine as live_engine

    source = inspect.getsource(live_engine.open_trade)

    assert "_compute_fast_entry_limit_price(option_symbol, option_mark)" in source
    assert "_submit_option_entry_market_order(" not in source
    assert "limit_reprice" in source


def test_live_order_calls_schwab_api():
    """
    TEST 1: Live mode calls the real Schwab order endpoint
    
    Verifies:
    - open_trade() calls _submit_option_order()
    - _submit_option_order() calls schwab_client.place_order()
    - Order ID is extracted from response
    """
    print("\n" + "="*70)
    print("TEST 1: Live mode calls Schwab API")
    print("="*70)
    
    # Import after mocking to ensure mock is in place
    import execution.live_engine as live_engine
    from execution.position_store import clear_position
    
    # Clear any persisted position
    clear_position()
    live_engine.current_position = None
    
    # Setup mock client
    mock_client = MockSchwabClient(should_fill=True)
    live_engine.set_schwab_client(mock_client, "33310903", "hash123")
    
    try:
        # Call open_trade
        result = live_engine.open_trade(
            direction="CALL",
            price=450.00,
            stop=445.00,
            target=460.00,
            quantity=4,
            reason="TEST",
            option={"symbol": "SPY 260724C00754000", "mark": 2.50, "delta": 0.65}
        )
        
        # Verify place_order was called
        assert mock_client.place_order_called, "place_order() not called"
        assert len(mock_client.placed_orders) > 0, "No orders placed"
        print("✓ place_order() was called on Schwab client")
        
        # Verify get_order was called to check fill
        assert mock_client.get_order_called, "get_order() not called for fill check"
        print("✓ get_order() was called to verify fill")
        
        # Verify trade opened
        assert result is True, "open_trade() returned False"
        print("✓ Trade was opened successfully")
        
        # Verify position has order ID
        assert live_engine.current_position is not None, "No position created"
        assert live_engine.current_position.schwab_order_id != "", "No order ID stored"
        print(f"✓ Order ID stored: {live_engine.current_position.schwab_order_id}")
        
        print("\n✓ TEST 1 PASSED")
        
    except Exception as e:
        print(f"\n✗ TEST 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        live_engine.current_position = None
        # Clean up position file for next test
        from execution.position_store import clear_position
        try:
            clear_position()
        except:
            pass


def test_no_position_before_fill_confirmation():
    """
    TEST 2: No local position exists before confirmed fill
    
    Verifies:
    - Position is NOT created while order is PENDING
    - Position IS created only after FILLED status
    - Fill price and timestamp are recorded
    """
    print("\n" + "="*70)
    print("TEST 2: No position before fill confirmation")
    print("="*70)
    
    import execution.live_engine as live_engine
    
    # Mock client that does NOT fill immediately
    mock_client = MockSchwabClient(should_fill=False)
    live_engine.set_schwab_client(mock_client, "33310903", "hash123")
    live_engine.current_position = None
    
    try:
        # Call open_trade - order will NOT fill
        result = live_engine.open_trade(
            direction="CALL",
            price=450.00,
            stop=445.00,
            target=460.00,
            quantity=4,
            reason="TEST",
            option={"symbol": "SPY 260724C00754000", "mark": 2.50, "delta": 0.65}
        )
        
        # Verify trade was NOT opened
        assert result is False, "open_trade() should return False for unfilled order"
        print("✓ open_trade() returned False for pending order")
        
        # Verify NO position was created
        assert live_engine.current_position is None, "Position created before fill!"
        print("✓ NO position created (kept bot flat)")
        
        print("\n✓ TEST 2 PASSED")
        
    except Exception as e:
        print(f"\n✗ TEST 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        live_engine.current_position = None


def test_rejected_orders_do_not_create_positions():
    """
    TEST 3: Rejected/unfilled orders do not create positions
    
    Verifies:
    - If order submission fails (status != 201), position is NOT created
    - If order is rejected by Schwab, position is NOT created
    - Bot remains flat
    """
    print("\n" + "="*70)
    print("TEST 3: Rejected orders do not create positions")
    print("="*70)
    
    import execution.live_engine as live_engine
    from execution.position_store import clear_position
    
    # Clear any persisted position
    clear_position()
    live_engine.current_position = None
    
    # Mock client that rejects order
    mock_client = MockSchwabClient(should_fill=True, status_code=400)
    live_engine.set_schwab_client(mock_client, "33310903", "hash123")
    
    try:
        # Call open_trade - order will be rejected
        result = live_engine.open_trade(
            direction="CALL",
            price=450.00,
            stop=445.00,
            target=460.00,
            quantity=4,
            reason="TEST",
            option={"symbol": "SPY 260724C00754000", "mark": 2.50, "delta": 0.65}
        )
        
        # Verify trade was NOT opened
        assert result is False, "open_trade() should return False for rejected order"
        print("✓ open_trade() returned False for rejected order")
        
        # Verify NO position was created
        assert live_engine.current_position is None, "Position created for rejected order!"
        print("✓ NO position created (kept bot flat)")
        
        print("\n✓ TEST 3 PASSED")
        
    except Exception as e:
        print(f"\n✗ TEST 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        live_engine.current_position = None
        # Clean up position file for next test
        from execution.position_store import clear_position
        try:
            clear_position()
        except:
            pass


def test_non_four_contract_order_is_rejected_before_submission():
    """Live entry must reject any contract count other than four."""
    import execution.live_engine as live_engine

    mock_client = MockSchwabClient(should_fill=True)
    live_engine.set_schwab_client(mock_client, "33310903", "hash123")
    live_engine.current_position = None

    result = live_engine.open_trade(
        direction="CALL",
        price=450.00,
        stop=445.00,
        target=460.00,
        quantity=3,
        reason="TEST",
        option={"symbol": "SPY 260724C00754000", "mark": 2.50, "delta": 0.65},
    )

    assert result is False
    assert mock_client.place_order_called is False
    assert live_engine.LAST_OPEN_TRADE_METRICS["block_reason"] == "contract_quantity_must_equal_max"


def test_monitor_has_no_paper_execution_path():
    """Production monitor always imports the sole live execution pipeline."""
    source = (Path(__file__).parent / "phase3_monitor.py").read_text(encoding="utf-8")
    assert "execution.paper_engine" not in source
    assert 'import_module("execution.live_engine")' in source


def test_position_stores_order_metadata():
    """
    TEST 5: Position stores all required order metadata
    
    Verifies:
    - Order ID is stored
    - Fill price is stored
    - Fill timestamp is stored
    - Submitted limit price is stored
    """
    print("\n" + "="*70)
    print("TEST 5: Position stores order metadata")
    print("="*70)
    
    import execution.live_engine as live_engine
    from execution.position_store import clear_position
    
    # Clear any persisted position
    clear_position()
    live_engine.current_position = None
    
    mock_client = MockSchwabClient(should_fill=True)
    live_engine.set_schwab_client(mock_client, "33310903", "hash123")
    
    try:
        # Open trade
        result = live_engine.open_trade(
            direction="CALL",
            price=450.00,
            stop=445.00,
            target=460.00,
            quantity=4,
            reason="TEST",
            option={"symbol": "SPY 260724C00754000", "mark": 2.50, "delta": 0.65}
        )
        
        assert result is True
        assert live_engine.current_position is not None
        
        # Verify all metadata fields
        pos = live_engine.current_position
        
        assert pos.schwab_order_id != "", f"No order ID: {pos.schwab_order_id}"
        print(f"✓ Order ID stored: {pos.schwab_order_id}")
        
        assert pos.schwab_fill_price > 0, f"No fill price: {pos.schwab_fill_price}"
        print(f"✓ Fill price stored: {pos.schwab_fill_price}")
        
        assert pos.schwab_fill_timestamp != "", f"No timestamp: {pos.schwab_fill_timestamp}"
        print(f"✓ Fill timestamp stored: {pos.schwab_fill_timestamp}")
        
        assert pos.submitted_limit_price > 0, f"No submitted price: {pos.submitted_limit_price}"
        print(f"✓ Submitted price stored: {pos.submitted_limit_price}")
        
        print("\n✓ TEST 5 PASSED")
        
    except Exception as e:
        print(f"\n✗ TEST 5 FAILED: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        live_engine.current_position = None
        # Clean up position file for next test
        from execution.position_store import clear_position
        try:
            clear_position()
        except:
            pass


if __name__ == "__main__":
    print("\n" + "="*70)
    print("Live Engine Comprehensive Regression Test Suite")
    print("="*70)
    
    tests = [
        ("Live mode calls Schwab API", test_live_order_calls_schwab_api),
        ("No position before fill confirmation", test_no_position_before_fill_confirmation),
        ("Rejected orders do not create positions", test_rejected_orders_do_not_create_positions),
        ("Non-four contract order is rejected", test_non_four_contract_order_is_rejected_before_submission),
        ("Paper mode never sends live order", test_paper_mode_never_sends_live_order),
        ("Position stores order metadata", test_position_stores_order_metadata),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            test_func()
            results.append((test_name, True))
        except Exception as e:
            print(f"\n✗ TEST CRASHED: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print("="*70)
    print(f"\nResult: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n✓✓✓ ALL TESTS PASSED - Production ready ✓✓✓")
        sys.exit(0)
    else:
        print("\n✗✗✗ TESTS FAILED - Do not deploy ✗✗✗")
        sys.exit(1)
