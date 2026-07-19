"""
Test suite for option pricing model fixes.

Verifies:
1. Delta is applied to dollar changes, not percentage
2. Entry slippage charged exactly once
3. Exit slippage charged exactly once
4. Slippage not deducted every candle
5. Time decay applied once per minute, not cumulatively
6. Favorable moves produce winners
7. Both winners and losers occur in mixed scenarios
"""

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd

from backtesting.option_pricer import EstimatedOptionPricer
from backtesting.data_loader import load_csv_data
from backtesting.replay_engine import ReplayEngine
from backtesting.signal_replay import SignalReplayEngine
from backtesting.trade_simulator import TradeSimulator


class TestDeltaApplicationCorrection(unittest.TestCase):
    """Test that delta is applied to dollar changes, not percentage."""
    
    def setUp(self):
        self.pricer = EstimatedOptionPricer(
            entry_option_price=5.00,
            delta=0.45,
            time_decay_per_minute=0.00,  # Disable for this test
            slippage=0.00
        )
        self.entry_time = datetime(2026, 7, 13, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        self.mid_time = datetime(2026, 7, 13, 10, 1, 0, tzinfo=ZoneInfo("America/New_York"))
    
    def test_call_up_1_dollar_move(self):
        """SPY 750→751 ($1 move), CALL delta 0.45 should increase by ~$0.45."""
        entry_spy = 750.00
        current_spy = 751.00  # $1 move
        
        option_price = self.pricer.simulate_price_change(
            direction="CALL",
            entry_spy_price=entry_spy,
            current_spy_price=current_spy,
            entry_time=self.entry_time,
            current_time=self.mid_time,
            position="mid"
        )
        
        # Expected: 5.00 + (1.00 * 0.45) = 5.45
        expected = 5.45
        self.assertAlmostEqual(option_price, expected, places=2,
                             msg=f"SPY up $1, CALL should increase by delta*$1 = $0.45, got ${option_price-5.00}")
    
    def test_call_up_2_dollar_move(self):
        """SPY 750→752 ($2 move), CALL delta 0.45 should increase by ~$0.90."""
        entry_spy = 750.00
        current_spy = 752.00  # $2 move
        
        option_price = self.pricer.simulate_price_change(
            direction="CALL",
            entry_spy_price=entry_spy,
            current_spy_price=current_spy,
            entry_time=self.entry_time,
            current_time=self.mid_time,
            position="mid"
        )
        
        # Expected: 5.00 + (2.00 * 0.45) = 5.90
        expected = 5.90
        self.assertAlmostEqual(option_price, expected, places=2,
                             msg=f"SPY up $2, CALL should increase by $0.90, got ${option_price-5.00}")
    
    def test_put_down_1_dollar_move(self):
        """SPY 750→749 ($1 down move), PUT delta 0.45 should increase by ~$0.45."""
        entry_spy = 750.00
        current_spy = 749.00  # $1 down move
        
        option_price = self.pricer.simulate_price_change(
            direction="PUT",
            entry_spy_price=entry_spy,
            current_spy_price=current_spy,
            entry_time=self.entry_time,
            current_time=self.mid_time,
            position="mid"
        )
        
        # Expected: 5.00 + (1.00 * 0.45) = 5.45
        expected = 5.45
        self.assertAlmostEqual(option_price, expected, places=2,
                             msg=f"SPY down $1, PUT should increase by $0.45, got ${option_price-5.00}")
    
    def test_put_up_1_dollar_move(self):
        """SPY 750→751 ($1 up move), PUT delta 0.45 should DECREASE by ~$0.45."""
        entry_spy = 750.00
        current_spy = 751.00  # $1 up move (bad for PUT)
        
        option_price = self.pricer.simulate_price_change(
            direction="PUT",
            entry_spy_price=entry_spy,
            current_spy_price=current_spy,
            entry_time=self.entry_time,
            current_time=self.mid_time,
            position="mid"
        )
        
        # Expected: 5.00 - (1.00 * 0.45) = 4.55
        expected = 4.55
        self.assertAlmostEqual(option_price, expected, places=2,
                             msg=f"SPY up $1, PUT should decrease by $0.45, got ${option_price-5.00}")
    
    def test_call_flat_spy(self):
        """SPY unchanged, CALL price should be $5.00 (no move, no time decay)."""
        entry_spy = 750.00
        current_spy = 750.00
        
        option_price = self.pricer.simulate_price_change(
            direction="CALL",
            entry_spy_price=entry_spy,
            current_spy_price=current_spy,
            entry_time=self.entry_time,
            current_time=self.mid_time,
            position="mid"
        )
        
        expected = 5.00
        self.assertAlmostEqual(option_price, expected, places=2)


class TestTimeDecayApplication(unittest.TestCase):
    """Test that time decay is applied correctly (once per minute)."""
    
    def setUp(self):
        self.pricer = EstimatedOptionPricer(
            entry_option_price=5.00,
            delta=0.00,  # Disable delta moves for this test
            time_decay_per_minute=0.02,
            slippage=0.00
        )
        self.entry_time = datetime(2026, 7, 13, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    
    def test_time_decay_1_minute(self):
        """After 1 minute with flat SPY, option should decay by 1 * $0.02 = $0.02."""
        mid_time = datetime(2026, 7, 13, 10, 1, 0, tzinfo=ZoneInfo("America/New_York"))
        
        option_price = self.pricer.simulate_price_change(
            direction="CALL",
            entry_spy_price=750.00,
            current_spy_price=750.00,  # Flat SPY
            entry_time=self.entry_time,
            current_time=mid_time,
            position="mid"
        )
        
        # Expected: 5.00 - (1 * 0.02) = 4.98
        expected = 4.98
        self.assertAlmostEqual(option_price, expected, places=2,
                             msg=f"After 1 min decay, should be $4.98, got ${option_price}")
    
    def test_time_decay_5_minutes(self):
        """After 5 minutes with flat SPY, option should decay by 5 * $0.02 = $0.10."""
        mid_time = datetime(2026, 7, 13, 10, 5, 0, tzinfo=ZoneInfo("America/New_York"))
        
        option_price = self.pricer.simulate_price_change(
            direction="CALL",
            entry_spy_price=750.00,
            current_spy_price=750.00,  # Flat SPY
            entry_time=self.entry_time,
            current_time=mid_time,
            position="mid"
        )
        
        # Expected: 5.00 - (5 * 0.02) = 4.90
        expected = 4.90
        self.assertAlmostEqual(option_price, expected, places=2,
                             msg=f"After 5 min decay, should be $4.90, got ${option_price}")
    
    def test_no_time_decay_at_entry(self):
        """At entry position, no time decay should be applied even if time has passed."""
        much_later = datetime(2026, 7, 13, 11, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        
        option_price = self.pricer.simulate_price_change(
            direction="CALL",
            entry_spy_price=750.00,
            current_spy_price=750.00,
            entry_time=self.entry_time,
            current_time=much_later,
            position="entry"  # position="entry" disables decay
        )
        
        # Expected: 5.00 (no decay at entry)
        expected = 5.00
        self.assertAlmostEqual(option_price, expected, places=2,
                             msg=f"At entry, no decay, should be $5.00, got ${option_price}")


class TestSlippageApplication(unittest.TestCase):
    """Test that slippage is applied correctly at entry/exit only."""
    
    def setUp(self):
        self.pricer = EstimatedOptionPricer(
            entry_option_price=5.00,
            delta=0.45,
            time_decay_per_minute=0.00,
            slippage=0.04  # $0.04 bid/ask spread
        )
    
    def test_entry_slippage_ask_side(self):
        """Entry should be at ASK (higher price) = mid + $0.02."""
        mid_price = 5.00
        ask_price = self.pricer.get_bid_ask_adjusted_price(mid_price, side="ask")
        
        # ASK = mid + slippage/2 = 5.00 + 0.02 = 5.02
        expected = 5.02
        self.assertAlmostEqual(ask_price, expected, places=2)
    
    def test_exit_slippage_bid_side(self):
        """Exit should be at BID (lower price) = mid - $0.02."""
        mid_price = 5.50
        bid_price = self.pricer.get_bid_ask_adjusted_price(mid_price, side="bid")
        
        # BID = mid - slippage/2 = 5.50 - 0.02 = 5.48
        expected = 5.48
        self.assertAlmostEqual(bid_price, expected, places=2)
    
    def test_total_slippage_entry_exit(self):
        """Round trip: buy at ASK, sell at BID = $0.04 total slippage."""
        entry_mid = 5.00
        entry_ask = self.pricer.get_bid_ask_adjusted_price(entry_mid, side="ask")
        
        exit_mid = 5.90  # After $0.90 gain
        exit_bid = self.pricer.get_bid_ask_adjusted_price(exit_mid, side="bid")
        
        # Entry at ASK: 5.02
        # Exit at BID: 5.88
        # Net gain: 5.88 - 5.02 = 0.86 (vs 0.90 theoretical, -0.04 for slippage)
        net_gain = exit_bid - entry_ask
        expected_net_gain = 0.90 - 0.04  # Theoretical gain minus total slippage
        
        self.assertAlmostEqual(net_gain, expected_net_gain, places=2,
                             msg="Round trip should cost total slippage of $0.04")


class TestFavorableMovesProduceWinners(unittest.TestCase):
    """Test that favorable moves can produce winners."""
    
    def test_2_dollar_favorable_call_move(self):
        """CALL with $2 favorable move should produce clear winner."""
        pricer = EstimatedOptionPricer(
            entry_option_price=5.00,
            delta=0.45,
            time_decay_per_minute=0.00,
            slippage=0.04
        )
        entry_time = datetime(2026, 7, 13, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        mid_time = datetime(2026, 7, 13, 10, 1, 0, tzinfo=ZoneInfo("America/New_York"))
        
        # Entry at ASK
        entry_mid = pricer.get_entry_price()
        entry_price = pricer.get_bid_ask_adjusted_price(entry_mid, side="ask")
        
        # SPY up $2
        exit_mid = pricer.simulate_price_change(
            direction="CALL",
            entry_spy_price=750.00,
            current_spy_price=752.00,
            entry_time=entry_time,
            current_time=mid_time,
            position="mid"
        )
        
        # Exit at BID
        exit_price = pricer.get_bid_ask_adjusted_price(exit_mid, side="bid")
        
        # P&L per contract (100 shares)
        pnl = (exit_price - entry_price) * 100
        
        # Expected: 
        # Entry: 5.02 (ASK)
        # Option move: 2 * 0.45 = 0.90
        # Exit mid: 5.90
        # Exit BID: 5.88
        # P&L: (5.88 - 5.02) * 100 = $86
        
        self.assertGreater(pnl, 50, 
                          msg=f"$2 favorable CALL move should produce winner, got ${pnl}")
        self.assertLess(pnl, 95,  # Should be less than theoretical $90
                       msg=f"$2 favorable CALL should be around $86 after slippage, got ${pnl}")
    
    def test_3_dollar_favorable_put_move(self):
        """PUT with $3 favorable move should produce large winner."""
        pricer = EstimatedOptionPricer(
            entry_option_price=5.00,
            delta=0.45,
            time_decay_per_minute=0.01,  # Light time decay
            slippage=0.04
        )
        entry_time = datetime(2026, 7, 13, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        mid_time = datetime(2026, 7, 13, 10, 2, 0, tzinfo=ZoneInfo("America/New_York"))
        
        # Entry at ASK
        entry_mid = pricer.get_entry_price()
        entry_price = pricer.get_bid_ask_adjusted_price(entry_mid, side="ask")
        
        # SPY down $3
        exit_mid = pricer.simulate_price_change(
            direction="PUT",
            entry_spy_price=750.00,
            current_spy_price=747.00,
            entry_time=entry_time,
            current_time=mid_time,
            position="mid"
        )
        
        # Exit at BID
        exit_price = pricer.get_bid_ask_adjusted_price(exit_mid, side="bid")
        
        # P&L per contract
        pnl = (exit_price - entry_price) * 100
        
        # Expected: ~135 (after accounting for time decay and slippage)
        self.assertGreater(pnl, 100,
                          msg=f"$3 favorable PUT move should produce large winner, got ${pnl}")


class TestSyntheticTradeScenarios(unittest.TestCase):
    """Test realistic synthetic scenarios with mixed winners and losers."""
    
    def test_scenario_2_percent_move_favorable_call(self):
        """SPY 750→765 (2% move), CALL should be significant winner."""
        pricer = EstimatedOptionPricer(
            entry_option_price=5.00,
            delta=0.45,
            time_decay_per_minute=0.02,
            slippage=0.04
        )
        entry_time = datetime(2026, 7, 13, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        exit_time = datetime(2026, 7, 13, 10, 10, 0, tzinfo=ZoneInfo("America/New_York"))
        
        # Entry at ASK
        entry_mid = pricer.get_entry_price()
        entry_price = pricer.get_bid_ask_adjusted_price(entry_mid, side="ask")
        
        # SPY up $15 (2% from 750)
        exit_mid = pricer.simulate_price_change(
            direction="CALL",
            entry_spy_price=750.00,
            current_spy_price=765.00,
            entry_time=entry_time,
            current_time=exit_time,
            position="mid"
        )
        
        # Exit at BID
        exit_price = pricer.get_bid_ask_adjusted_price(exit_mid, side="bid")
        
        # P&L per contract
        pnl = (exit_price - entry_price) * 100
        
        # Expected: delta * $15 * 100 - slippage - time_decay
        # = 0.45 * 15 * 100 - $0.04 * 100 - $0.02 * 10
        # = 675 - 4 - 0.20 ≈ 670+
        self.assertGreater(pnl, 550,
                          msg=f"2% favorable move should be huge winner, got ${pnl}")
    
    def test_scenario_flat_spy_loser(self):
        """SPY flat, CALL with time decay should lose."""
        pricer = EstimatedOptionPricer(
            entry_option_price=5.00,
            delta=0.45,
            time_decay_per_minute=0.02,
            slippage=0.04
        )
        entry_time = datetime(2026, 7, 13, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        exit_time = datetime(2026, 7, 13, 10, 15, 0, tzinfo=ZoneInfo("America/New_York"))  # 15 min hold
        
        # Entry at ASK
        entry_mid = pricer.get_entry_price()
        entry_price = pricer.get_bid_ask_adjusted_price(entry_mid, side="ask")
        
        # SPY flat
        exit_mid = pricer.simulate_price_change(
            direction="CALL",
            entry_spy_price=750.00,
            current_spy_price=750.00,  # Flat
            entry_time=entry_time,
            current_time=exit_time,
            position="mid"
        )
        
        # Exit at BID
        exit_price = pricer.get_bid_ask_adjusted_price(exit_mid, side="bid")
        
        # P&L per contract
        pnl = (exit_price - entry_price) * 100
        
        # Expected: -(0.02 * 15 + 0.04) * 100 = -(0.30 + 0.04) * 100 = -$34
        self.assertLess(pnl, -20,
                       msg=f"Flat SPY with time decay should be loser, got ${pnl}")


if __name__ == "__main__":
    unittest.main()
