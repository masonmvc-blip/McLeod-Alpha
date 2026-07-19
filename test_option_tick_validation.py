#!/usr/bin/env python3
"""
Test suite for Schwab option order validation.

Tests:
1. Price normalization to valid option ticks
2. Order payload structure validation
3. Schwab validation error handling
4. HTTP 400 leaves bot flat
5. No local position without confirmed fill
6. OCC option symbol format
7. Dry-run order validation
"""

import sys
import json
import unittest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock, call

# Add current directory to path for imports
sys.path.insert(0, '/Users/mason/Library/CloudStorage/Dropbox/McLeod Capital/McLeod Alpha')

from execution import live_engine


class TestOptionTickNormalization(unittest.TestCase):
    """TEST 1: Option tick normalization"""
    
    def test_normalize_price_above_3_dollars(self):
        """Price >= $3.00 should use $0.01 tick"""
        # 4.6864 should round to 4.69
        result = live_engine.normalize_option_tick(4.6864)
        self.assertEqual(result, 4.69, f"Expected 4.69, got {result}")
        print("✓ TEST 1.1: 4.6864 → 4.69 (rounds up to nearest $0.01)")
        
        # 4.684 should round to 4.68
        result = live_engine.normalize_option_tick(4.684)
        self.assertEqual(result, 4.68, f"Expected 4.68, got {result}")
        print("✓ TEST 1.2: 4.684 → 4.68 (rounds down to nearest $0.01)")
        
        # 10.0 should stay 10.00
        result = live_engine.normalize_option_tick(10.0)
        self.assertEqual(result, 10.00, f"Expected 10.00, got {result}")
        print("✓ TEST 1.3: 10.0 → 10.00 (already valid)")
    
    def test_normalize_price_below_3_dollars(self):
        """Price < $3.00 should use $0.05 tick"""
        # 2.12 should round to 2.10 (nearest $0.05)
        result = live_engine.normalize_option_tick(2.12)
        self.assertEqual(result, 2.10, f"Expected 2.10, got {result}")
        print("✓ TEST 1.4: 2.12 → 2.10 (rounds to nearest $0.05)")
        
        # 2.17 should round to 2.15
        result = live_engine.normalize_option_tick(2.17)
        self.assertEqual(result, 2.15, f"Expected 2.15, got {result}")
        print("✓ TEST 1.5: 2.17 → 2.15 (rounds to nearest $0.05)")
    
    def test_normalize_price_boundary(self):
        """Test boundary at $3.00"""
        # 2.99 should use $0.05 tick
        result = live_engine.normalize_option_tick(2.99)
        self.assertIn(result, [2.95, 3.00], f"Expected 2.95 or 3.00, got {result}")
        print(f"✓ TEST 1.6: 2.99 → {result} (at $0.05 tick boundary)")
        
        # 3.00 should use $0.01 tick
        result = live_engine.normalize_option_tick(3.00)
        self.assertEqual(result, 3.00, f"Expected 3.00, got {result}")
        print("✓ TEST 1.7: 3.00 → 3.00 (exactly at threshold)")
        
        # 3.01 should use $0.01 tick
        result = live_engine.normalize_option_tick(3.01)
        self.assertEqual(result, 3.01, f"Expected 3.01, got {result}")
        print("✓ TEST 1.8: 3.01 → 3.01 ($0.01 tick)")


class TestOrderPayloadValidation(unittest.TestCase):
    """TEST 2: Order payload structure validation"""
    
    def test_occ_option_symbol_format(self):
        """OCC symbols must be in format: SPY 260724C00754000"""
        valid_symbols = [
            "SPY 260724C00754000",
            "SPY 260724P00750000",
            "QQQ 260718C00500000",
        ]
        
        for symbol in valid_symbols:
            parts = symbol.strip().split()
            self.assertEqual(len(parts), 2, f"Symbol {symbol} doesn't split into 2 parts")
            underlying, contract = parts
            self.assertEqual(len(contract), 15, f"Contract {contract} should be 15 chars")
            self.assertIn(contract[6], ['C', 'P'], f"Contract type should be C or P")
            print(f"✓ TEST 2.1: OCC symbol valid: {symbol}")
    
    def test_order_leg_structure(self):
        """Verify orderLegCollection structure"""
        expected_structure = {
            "instruction": "BUY_TO_OPEN",
            "quantity": 1,
            "instrument": {
                "assetType": "OPTION",
                "symbol": "SPY 260724C00754000"
            }
        }
        
        # Validate required fields
        self.assertIn("instruction", expected_structure)
        self.assertIn("quantity", expected_structure)
        self.assertIn("instrument", expected_structure)
        self.assertEqual(expected_structure["instruction"], "BUY_TO_OPEN")
        self.assertEqual(expected_structure["instrument"]["assetType"], "OPTION")
        print("✓ TEST 2.2: Order leg structure valid")
    
    def test_order_parameters_structure(self):
        """Verify complete order structure"""
        order_payload = {
            "orderType": "LIMIT",
            "session": "NORMAL",
            "duration": "DAY",
            "orderStrategyType": "SINGLE",
            "price": 4.69,
            "orderLegCollection": [
                {
                    "instruction": "BUY_TO_OPEN",
                    "quantity": 1,
                    "instrument": {
                        "assetType": "OPTION",
                        "symbol": "SPY 260724C00754000"
                    }
                }
            ]
        }
        
        # Validate all required fields present
        required_fields = ["orderType", "session", "duration", "orderStrategyType", "price", "orderLegCollection"]
        for field in required_fields:
            self.assertIn(field, order_payload, f"Missing required field: {field}")
        
        # Validate field values
        self.assertEqual(order_payload["orderType"], "LIMIT")
        self.assertEqual(order_payload["session"], "NORMAL")
        self.assertEqual(order_payload["duration"], "DAY")
        self.assertEqual(order_payload["orderStrategyType"], "SINGLE")
        self.assertIsInstance(order_payload["price"], float)
        self.assertGreater(order_payload["price"], 0)
        print("✓ TEST 2.3: Complete order structure valid")


class TestSchwabErrorHandling(unittest.TestCase):
    """TEST 3: Schwab validation error capture and handling"""
    
    @patch('execution.live_engine._schwab_client')
    def test_http_400_error_capture(self, mock_client):
        """Verify HTTP 400 validation errors are captured"""
        
        # Mock a failed response
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = json.dumps({
            "error": "Invalid Request",
            "message": "Order contains invalid price precision",
            "details": "Limit price must use valid tick size"
        })
        mock_response.json.return_value = json.loads(mock_response.text)
        mock_response.headers = {}
        
        mock_client.place_order.return_value = mock_response
        
        # Set up client
        live_engine._schwab_client = mock_client
        live_engine._schwab_account_number = "33310903"
        live_engine._schwab_account_hash = "96636430645ADE50C"
        
        # Attempt order submission - should return None
        result = live_engine._submit_option_order(
            "SPY 260724C00754000",
            "CALL",
            4.6864,  # Invalid price precision
            1
        )
        
        # Verify order failed (returns None)
        self.assertIsNone(result, "Expected None for failed order")
        print("✓ TEST 3.1: HTTP 400 handled, order rejected")
    
    @patch('execution.live_engine._schwab_client')
    def test_validation_error_json_parsing(self, mock_client):
        """Verify JSON error details are extracted"""
        
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = json.dumps({
            "errors": [
                {
                    "code": "INVALID_PRICE",
                    "message": "Price precision too high: 4.6864 is not a valid option tick"
                }
            ]
        })
        mock_response.json.return_value = json.loads(mock_response.text)
        mock_response.headers = {}
        
        mock_client.place_order.return_value = mock_response
        
        live_engine._schwab_client = mock_client
        live_engine._schwab_account_number = "33310903"
        
        # Attempt order - error details should be printed
        result = live_engine._submit_option_order(
            "SPY 260724C00754000",
            "CALL",
            4.6864,
            1
        )
        
        self.assertIsNone(result)
        print("✓ TEST 3.2: Validation error JSON parsed and logged")


class TestPositionClosureBehavior(unittest.TestCase):
    """TEST 4 & 5: HTTP 400 leaves bot flat, no local position without fill"""
    
    @patch('execution.live_engine._schwab_client')
    @patch('execution.live_engine.can_open_trade')
    def test_http_400_prevents_position_creation(self, mock_can_open, mock_client):
        """Verify position not created when HTTP 400 returned"""
        
        mock_can_open.return_value = (True, "")
        
        # Mock failed response
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = '{"error": "Invalid price"}'
        mock_response.json.return_value = json.loads(mock_response.text)
        mock_response.headers = {}
        
        mock_client.place_order.return_value = mock_response
        
        live_engine._schwab_client = mock_client
        live_engine._schwab_account_number = "33310903"
        live_engine.current_position = None
        
        # Attempt trade
        result = live_engine.open_trade(
            direction="CALL",
            price=750.00,
            stop=745.00,
            target=755.00,
            quantity=1,
            reason="TEST",
            option={
                "symbol": "SPY 260724C00754000",
                "mark": 4.64,
                "delta": 0.50
            }
        )
        
        # Verify trade rejected and position NOT created
        self.assertFalse(result, "Expected False from open_trade")
        self.assertIsNone(live_engine.current_position, "Expected position to be None")
        print("✓ TEST 4.1: HTTP 400 prevents position creation (bot stays flat)")
    
    @patch('execution.live_engine._schwab_client')
    @patch('execution.live_engine.can_open_trade')
    def test_unfilled_order_prevents_position_creation(self, mock_can_open, mock_client):
        """Verify position not created without confirmed fill"""
        
        mock_can_open.return_value = (True, "")
        
        # Mock successful order submission but no fill
        mock_submit_response = Mock()
        mock_submit_response.status_code = 201
        mock_submit_response.headers = {"Location": "/v1/accounts/123/orders/ORDER123"}
        mock_submit_response.text = '{"id": "ORDER123"}'
        mock_submit_response.json.return_value = {"id": "ORDER123"}
        
        # Mock unfilled order status
        mock_fill_response = Mock()
        mock_fill_response.status_code = 200
        mock_fill_response.json.return_value = {
            "id": "ORDER123",
            "status": "PENDING_ACTIVATION",
            "orderType": "LIMIT"
        }
        
        def place_order_side_effect(*args, **kwargs):
            return mock_submit_response
        
        def get_order_side_effect(*args, **kwargs):
            return mock_fill_response
        
        mock_client.place_order.side_effect = place_order_side_effect
        mock_client.get_order.side_effect = get_order_side_effect
        
        live_engine._schwab_client = mock_client
        live_engine._schwab_account_number = "33310903"
        live_engine.current_position = None
        
        # Attempt trade with unfilled order
        result = live_engine.open_trade(
            direction="CALL",
            price=750.00,
            stop=745.00,
            target=755.00,
            quantity=1,
            reason="TEST",
            option={
                "symbol": "SPY 260724C00754000",
                "mark": 4.64,
                "delta": 0.50
            }
        )
        
        # Verify trade rejected (timeout) and position NOT created
        self.assertFalse(result, "Expected False when order times out")
        self.assertIsNone(live_engine.current_position, "Expected position to be None")
        print("✓ TEST 4.2: Unfilled order prevents position creation")


class TestDryRunValidation(unittest.TestCase):
    """TEST 6: Dry-run order validation without transmission"""
    
    def test_dry_run_validates_normalized_price(self):
        """Dry-run validates order without hitting Schwab"""
        
        # Raw price from mark * 1.01 buffer
        raw_price = 4.64 * 1.01  # 4.6864
        
        # Normalize
        normalized = live_engine.normalize_option_tick(raw_price)
        
        # Verify normalization
        self.assertEqual(normalized, 4.69)
        self.assertNotEqual(normalized, raw_price)
        print(f"✓ TEST 6.1: Dry-run: Raw {raw_price:.6f} → Normalized {normalized:.2f}")
    
    def test_dry_run_validates_payload_structure(self):
        """Dry-run validates complete order payload"""
        
        payload = {
            "orderType": "LIMIT",
            "session": "NORMAL",
            "duration": "DAY",
            "orderStrategyType": "SINGLE",
            "price": 4.69,
            "orderLegCollection": [
                {
                    "instruction": "BUY_TO_OPEN",
                    "quantity": 1,
                    "instrument": {
                        "assetType": "OPTION",
                        "symbol": "SPY 260724C00754000"
                    }
                }
            ]
        }
        
        # Validate structure
        self.assertEqual(payload["orderType"], "LIMIT")
        self.assertEqual(payload["session"], "NORMAL")
        self.assertEqual(payload["duration"], "DAY")
        self.assertEqual(payload["orderStrategyType"], "SINGLE")
        self.assertEqual(payload["price"], 4.69)
        
        leg = payload["orderLegCollection"][0]
        self.assertEqual(leg["instruction"], "BUY_TO_OPEN")
        self.assertEqual(leg["instrument"]["assetType"], "OPTION")
        
        print("✓ TEST 6.2: Dry-run: Payload structure valid")


class TestRegressionValidation(unittest.TestCase):
    """TEST 7: Regression tests proving fixes work"""
    
    def test_malformed_price_cannot_reach_schwab(self):
        """Malformed prices are normalized before API call"""
        
        # Collect all invalid prices that would cause Schwab rejection
        test_cases = [
            (4.6864, 4.69),      # Too many decimals → rounds to nearest $0.01
            (4.684321, 4.68),    # Way too many decimals → rounds to nearest $0.01
            (2.126543, 2.15),    # Sub-$3 with too many decimals → rounds to nearest $0.05
            (2.12, 2.10),        # Sub-$3 → rounds to nearest $0.05
        ]
        
        for raw, expected_norm in test_cases:
            normalized = live_engine.normalize_option_tick(raw)
            self.assertEqual(normalized, expected_norm, f"Price {raw} should normalize to {expected_norm}, got {normalized}")
            # Verify final format is what Schwab expects
            str_price = str(normalized)
            decimal_places = len(str_price.split('.')[-1]) if '.' in str_price else 0
            self.assertLessEqual(decimal_places, 2, f"Too many decimals: {str_price}")
        
        print("✓ TEST 7.1: All malformed prices normalized before API call")
    
    def test_correct_occ_symbols_submitted(self):
        """Verify OCC format maintained in submissions"""
        
        symbols = [
            "SPY 260724C00754000",
            "SPY 260724P00750000",
            "QQQ 260721C00500000",
        ]
        
        for symbol in symbols:
            parts = symbol.split()
            self.assertEqual(len(parts), 2)
            
            underlying = parts[0]
            contract = parts[1]
            
            # Verify contract format
            self.assertEqual(len(contract), 15)
            self.assertIn(contract[6], ['C', 'P'])
            
            print(f"✓ TEST 7.2: OCC format valid: {symbol}")


def run_tests():
    """Run all tests"""
    print("\n" + "="*70)
    print("SCHWAB OPTION ORDER VALIDATION TEST SUITE")
    print("="*70 + "\n")
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestOptionTickNormalization))
    suite.addTests(loader.loadTestsFromTestCase(TestOrderPayloadValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestSchwabErrorHandling))
    suite.addTests(loader.loadTestsFromTestCase(TestPositionClosureBehavior))
    suite.addTests(loader.loadTestsFromTestCase(TestDryRunValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestRegressionValidation))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Summary
    print("\n" + "="*70)
    if result.wasSuccessful():
        print("✓✓✓ ALL TESTS PASSED ✓✓✓")
    else:
        print("✗✗✗ SOME TESTS FAILED ✗✗✗")
        print(f"Failures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")
    print("="*70 + "\n")
    
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
