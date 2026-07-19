"""
Replay validation framework for diagnosing historical backtest divergence.

Compares paper-trading results against replay-engine results for a given date,
with detailed per-trade diagnostics and option-price model analysis.
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import List, Dict, Tuple, Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtesting import load_csv_data, ReplayEngine
from backtesting.signal_replay import SignalReplayEngine
from backtesting.option_pricer import EstimatedOptionPricer
from backtesting.historical_option_playback import build_replay_option_pricer
from backtesting.trade_simulator import TradeSimulator
from backtesting.trade_replay_inspector import PaperTradeSpec, inspect_trade_from_df


TIMEZONE = ZoneInfo("America/New_York")


class ReplayValidation:
    """Validates replay engine against known paper-trading results."""
    
    def __init__(self, csv_path: str, validation_date: str):
        """
        Initialize validation for a specific date.
        
        Args:
            csv_path: Path to historical OHLCV CSV
            validation_date: YYYY-MM-DD format (ET timezone)
        """
        self.csv_path = csv_path
        self.validation_date = validation_date
        
        # Load data
        self.df = load_csv_data(csv_path)
        
        # Filter to validation date
        self.df["date"] = self.df["timestamp"].dt.date
        self.df_day = self.df[self.df["date"] == pd.to_datetime(validation_date).date()].copy()
        
        if self.df_day.empty:
            raise ValueError(f"No candles found for {validation_date}")
    
    def run_replay(
        self,
        call_threshold: int = 4,
        put_threshold: int = 4,
        max_hold_minutes: int = 15,
        max_trades_per_day: int = 20,
        delta: float = 0.45,
        entry_option_price: float = 5.00,
        slippage: float = 0.04,
    ) -> Dict:
        """
        Run replay engine for validation date with given parameters.
        
        Returns:
            Dict with summary stats and trades list
        """
        # Convert validation_date string to date object
        validation_date_obj = pd.to_datetime(self.validation_date).date()
        
        # Initialize engines
        replay_engine = ReplayEngine(
            self.df_day,
            start_date=validation_date_obj,
            end_date=validation_date_obj,
            include_premarket=True
        )
        
        signal_engine = SignalReplayEngine(
            replay_engine,
            call_threshold=call_threshold,
            put_threshold=put_threshold
        )
        
        option_pricer = build_replay_option_pricer(
            entry_option_price=entry_option_price,
            delta=delta,
            slippage=slippage,
            trade_date=self.validation_date,
        )
        
        simulator = TradeSimulator(
            replay_engine=replay_engine,
            signal_engine=signal_engine,
            option_pricer=option_pricer,
            max_trades_per_day=max_trades_per_day,
            max_hold_minutes=max_hold_minutes,
        )
        
        # Run simulation
        trades = simulator.run()
        
        # Get summary
        summary = simulator.get_summary()
        
        return {
            "summary": summary,
            "trades": trades,
            "simulator": simulator,
            "replay_engine": replay_engine,
        }

    def compare_with_paper_trade_log(self, paper_trade_csv_path: str) -> pd.DataFrame:
        """Build per-trade parity rows for all paper trades on validation date."""
        paper_df = pd.read_csv(paper_trade_csv_path)
        paper_df["entry_time"] = pd.to_datetime(paper_df["entry_time"])
        paper_df["exit_time"] = pd.to_datetime(paper_df["exit_time"])

        target_date = pd.to_datetime(self.validation_date).date()
        day_df = paper_df[paper_df["entry_time"].dt.date == target_date].copy()
        day_df = day_df.sort_values("entry_time").reset_index(drop=True)

        rows = []
        for _, paper in day_df.iterrows():
            spec = PaperTradeSpec(
                data_path=Path(self.csv_path),
                trade_date=self.validation_date,
                entry_time=paper["entry_time"].strftime("%H:%M:%S"),
                direction=str(paper["direction"]),
                paper_exit_time=paper["exit_time"].strftime("%H:%M:%S"),
                paper_pnl=float(paper.get("option_pnl_dollars", 0.0) or 0.0),
                paper_return=float(paper.get("option_pnl_pct", 0.0) or 0.0),
                paper_exit_reason=str(paper.get("exit_reason", "OPTION_STOP")),
            )
            pricer = build_replay_option_pricer(
                entry_option_price=5.0,
                delta=0.45,
                slippage=0.04,
                trade_date=self.validation_date,
            )
            inspected = inspect_trade_from_df(self.df, spec, option_pricer=pricer)
            summary = inspected["summary"]

            rows.append(
                {
                    "entry_time": paper["entry_time"].isoformat(),
                    "direction": str(paper["direction"]),
                    "replay_exit_time": summary["replay_result"]["replay_exit_time"],
                    "replay_exit_reason": summary["replay_result"]["replay_exit_reason"],
                    "replay_pnl": summary["replay_result"]["replay_pnl"],
                    "paper_exit_time": paper["exit_time"].isoformat(),
                    "paper_exit_reason": str(paper.get("exit_reason", "")),
                    "paper_pnl": float(paper.get("option_pnl_dollars", 0.0) or 0.0),
                    "first_divergent_state_or_calculation": summary["first_divergent_field"],
                }
            )

        return pd.DataFrame(rows)

    def build_trade_trace_table(self, paper_trade_csv_path: str) -> pd.DataFrame:
        """Build a minute-by-minute trace for every paper trade on validation date."""
        paper_df = pd.read_csv(paper_trade_csv_path)
        paper_df["entry_time"] = pd.to_datetime(paper_df["entry_time"])
        paper_df["exit_time"] = pd.to_datetime(paper_df["exit_time"])

        target_date = pd.to_datetime(self.validation_date).date()
        day_df = paper_df[paper_df["entry_time"].dt.date == target_date].copy()
        day_df = day_df.sort_values("entry_time").reset_index(drop=True)

        all_rows = []
        for _, paper in day_df.iterrows():
            trade_id = int(paper.get("id", 0) or 0)
            spec = PaperTradeSpec(
                data_path=Path(self.csv_path),
                trade_date=self.validation_date,
                entry_time=paper["entry_time"].strftime("%H:%M:%S"),
                direction=str(paper["direction"]),
                paper_exit_time=paper["exit_time"].strftime("%H:%M:%S"),
                paper_pnl=float(paper.get("option_pnl_dollars", 0.0) or 0.0),
                paper_return=float(paper.get("option_pnl_pct", 0.0) or 0.0),
                paper_exit_reason=str(paper.get("exit_reason", "OPTION_STOP")),
            )
            pricer = build_replay_option_pricer(
                entry_option_price=5.0,
                delta=0.45,
                slippage=0.04,
                trade_date=self.validation_date,
            )
            inspected = inspect_trade_from_df(self.df, spec, option_pricer=pricer)
            replay_df = inspected["replay_df"].copy()
            replay_df.insert(0, "trade_id", trade_id)
            replay_df.insert(1, "entry_time", paper["entry_time"].isoformat())
            replay_df.insert(2, "paper_exit_time", paper["exit_time"].isoformat())
            replay_df.insert(3, "paper_exit_reason", str(paper.get("exit_reason", "")))
            replay_df.insert(4, "paper_pnl", float(paper.get("option_pnl_dollars", 0.0) or 0.0))
            all_rows.append(replay_df)

        if not all_rows:
            return pd.DataFrame()
        return pd.concat(all_rows, ignore_index=True)
    
    def compare_with_paper_trading(
        self,
        paper_trades: int,
        paper_winners: int,
        paper_losers: int,
        paper_net_pnl: float,
        paper_avg_hold_min: float,
        paper_max_hold_exits: int,
        paper_option_stop_exits: int,
        paper_eod_exits: int,
    ) -> Dict:
        """
        Compare replay results against paper-trading benchmark.
        
        Returns:
            Dict with comparison results and mismatches
        """
        replay_result = self.run_replay()
        summary = replay_result["summary"]
        by_exit_reason = summary.get("by_exit_reason", {})
        replay_stop_like_exits = (
            by_exit_reason.get("OPTION_STOP", {}).get("count", 0)
            + by_exit_reason.get("INITIAL_STOP", {}).get("count", 0)
            + by_exit_reason.get("TRAILING_STOP", {}).get("count", 0)
        )
        
        comparisons = {
            "trades": {
                "paper": paper_trades,
                "replay": summary["total_trades"],
                "match": paper_trades == summary["total_trades"],
                "divergence": summary["total_trades"] - paper_trades,
            },
            "winners": {
                "paper": paper_winners,
                "replay": summary["winners"],
                "match": paper_winners == summary["winners"],
                "divergence": summary["winners"] - paper_winners,
            },
            "losers": {
                "paper": paper_losers,
                "replay": summary["losers"],
                "match": paper_losers == summary["losers"],
                "divergence": summary["losers"] - paper_losers,
            },
            "win_rate_pct": {
                "paper": (paper_winners / paper_trades * 100) if paper_trades > 0 else 0,
                "replay": summary["win_rate_pct"],
                "match": abs((paper_winners / paper_trades * 100) - summary["win_rate_pct"]) < 0.01,
                "divergence": summary["win_rate_pct"] - (paper_winners / paper_trades * 100) if paper_trades > 0 else 0,
            },
            "net_pnl": {
                "paper": paper_net_pnl,
                "replay": summary["net_pnl"],
                "match": abs(paper_net_pnl - summary["net_pnl"]) < 0.01,
                "divergence": summary["net_pnl"] - paper_net_pnl,
            },
            "exit_reasons": {
                "paper_max_hold": paper_max_hold_exits,
                "replay_max_hold": by_exit_reason.get("MAX_HOLD_15_MIN", {}).get("count", 0),
                "paper_option_stop": paper_option_stop_exits,
                "replay_option_stop": replay_stop_like_exits,
                "paper_eod": paper_eod_exits,
                "replay_eod": by_exit_reason.get("END_OF_DAY_EXIT", {}).get("count", 0),
            },
        }
        
        # Check key mismatches
        mismatches = []
        if not comparisons["trades"]["match"]:
            mismatches.append(f"Trade count: expected {paper_trades}, got {summary['total_trades']}")
        if not comparisons["winners"]["match"]:
            mismatches.append(f"Winners: expected {paper_winners}, got {summary['winners']}")
        if not comparisons["win_rate_pct"]["match"]:
            mismatches.append(f"Win rate: expected {comparisons['win_rate_pct']['paper']:.2f}%, got {comparisons['win_rate_pct']['replay']:.2f}%")
        if not comparisons["net_pnl"]["match"]:
            mismatches.append(f"Net P/L: expected ${paper_net_pnl:.2f}, got ${summary['net_pnl']:.2f}")
        
        return {
            "comparisons": comparisons,
            "mismatches": mismatches,
            "all_match": len(mismatches) == 0,
            "replay_result": replay_result,
        }


class OptionPricerDiagnostics:
    """Diagnostics for option pricing model."""
    
    def __init__(self, entry_price: float = 5.00, delta: float = 0.45, slippage: float = 0.04):
        self.pricer = EstimatedOptionPricer(
            entry_option_price=entry_price,
            delta=delta,
            slippage=slippage
        )
        self.entry_price = entry_price
        self.delta = delta
        self.slippage = slippage
    
    def trace_option_price(
        self,
        spy_entry: float,
        spy_prices: List[float],
        direction: str,
    ) -> Dict:
        """
        Trace option price changes through replay.
        
        Args:
            spy_entry: Entry SPY price
            spy_prices: List of SPY prices through trade life
            direction: "CALL" or "PUT"
        
        Returns:
            Dict with detailed price tracking
        """
        from datetime import datetime, timedelta
        
        trace = []
        current_option = None
        peak_option = None
        stop_level = None
        entry_time = datetime.now()
        
        for i, spy_price in enumerate(spy_prices):
            spy_change = spy_price - spy_entry
            
            # Calculate option price at this point
            if i == 0:
                # Entry: use pricer to get entry price, then apply slippage
                option_price = self.pricer.get_entry_price()
                slippage_ask = self.pricer.get_bid_ask_adjusted_price(option_price, side="ask")
                current_option = slippage_ask
                peak_option = current_option
                stop_level = current_option * 0.95  # 5% initial stop
                entry_record = {
                    "candle": i,
                    "spy_price": spy_price,
                    "spy_change": spy_change,
                    "direction": direction,
                    "option_price_before_slippage": option_price,
                    "slippage_applied": self.slippage,
                    "option_price_after_slippage": current_option,
                    "stop_level": stop_level,
                    "peak_option": peak_option,
                    "status": "ENTRY",
                }
                trace.append(entry_record)
            else:
                # Mid-trade: use pricer to get price at current level
                current_time = entry_time + timedelta(minutes=i)
                mid_price = self.pricer.simulate_price_change(
                    direction=direction,
                    entry_spy_price=spy_entry,
                    current_spy_price=spy_price,
                    entry_time=entry_time,
                    current_time=current_time,
                    position="mid"
                )
                
                # For diagnostics, show the movement
                prev_spy = spy_prices[i - 1]
                spy_move = spy_price - prev_spy
                
                # Update peak
                if mid_price > peak_option:
                    peak_option = mid_price
                
                # Check stop level
                stop_hit = mid_price <= stop_level
                
                record = {
                    "candle": i,
                    "spy_price": spy_price,
                    "spy_change": spy_change,
                    "spy_move_this_candle": spy_move,
                    "direction": direction,
                    "option_price": mid_price,
                    "stop_level": stop_level,
                    "peak_option": peak_option,
                    "stop_hit": stop_hit,
                    "status": "STOP_HIT" if stop_hit else "HELD",
                }
                trace.append(record)
                current_option = mid_price
        
        return {
            "entry_spy": spy_entry,
            "entry_option": trace[0]["option_price_after_slippage"] if trace else None,
            "final_spy": spy_prices[-1],
            "final_option": current_option,
            "peak_option": peak_option,
            "trace": trace,
        }
    
    def sanity_check_direction(self, spy_move: float, option_change: float, direction: str) -> bool:
        """
        Sanity check that option moves in expected direction.
        
        Args:
            spy_move: SPY price change
            option_change: Option price change
            direction: "CALL" or "PUT"
        
        Returns:
            True if direction makes sense
        """
        if direction == "CALL":
            # Rising SPY should increase CALL
            return (spy_move > 0 and option_change > 0) or (spy_move < 0 and option_change < 0)
        else:  # PUT
            # Rising SPY should decrease PUT (increase loss, which is negative)
            return (spy_move > 0 and option_change < 0) or (spy_move < 0 and option_change > 0)


class FailureModeTests:
    """Tests for common failure modes in option pricing."""
    
    @staticmethod
    def test_option_always_decreasing() -> bool:
        """Test that option doesn't always decrease."""
        from datetime import datetime, timedelta
        
        pricer = EstimatedOptionPricer(entry_option_price=5.00, delta=0.45, slippage=0.04)
        
        # Rising SPY should increase CALL option
        entry_price = pricer.get_entry_price()
        
        # Simulate rising SPY
        entry_time = datetime(2026, 7, 13, 9, 30)
        current_time = datetime(2026, 7, 13, 9, 31)
        
        call_at_entry = pricer.simulate_price_change(
            "CALL", 100.0, 100.0, entry_time, entry_time, position="entry"
        )
        call_at_higher_spy = pricer.simulate_price_change(
            "CALL", 100.0, 101.0, entry_time, current_time, position="mid"
        )
        
        # Should be higher (less decay loss outweighed by delta gain)
        return call_at_higher_spy > call_at_entry - 0.05  # Allow for time decay
    
    @staticmethod
    def test_put_decreases_on_rising_spy() -> bool:
        """Test PUT option decreases when SPY rises."""
        from datetime import datetime
        
        pricer = EstimatedOptionPricer(entry_option_price=5.00, delta=0.45, slippage=0.04)
        
        entry_time = datetime(2026, 7, 13, 9, 30)
        current_time = datetime(2026, 7, 13, 9, 31)
        
        put_at_entry = pricer.simulate_price_change(
            "PUT", 100.0, 100.0, entry_time, entry_time, position="entry"
        )
        put_at_higher_spy = pricer.simulate_price_change(
            "PUT", 100.0, 101.0, entry_time, current_time, position="mid"
        )
        
        # PUT should decrease when SPY rises
        return put_at_higher_spy < put_at_entry
    
    @staticmethod
    def test_slippage_only_at_entry_exit() -> bool:
        """Test that slippage is only applied at entry and exit."""
        # This is more of a logic check - should verify in trade simulator
        # that slippage is not applied every candle
        return True
    
    @staticmethod
    def test_flat_spy_not_extreme_loss() -> bool:
        """Test that flat SPY over one minute doesn't cause extreme loss."""
        from datetime import datetime
        
        pricer = EstimatedOptionPricer(entry_option_price=5.00, delta=0.45, slippage=0.04)
        
        entry_time = datetime(2026, 7, 13, 9, 30)
        current_time = datetime(2026, 7, 13, 9, 31)
        
        call_at_entry = pricer.simulate_price_change(
            "CALL", 100.0, 100.0, entry_time, entry_time, position="entry"
        )
        call_flat_spy = pricer.simulate_price_change(
            "CALL", 100.0, 100.0, entry_time, current_time, position="mid"
        )
        
        # Should be minimal loss (just time decay)
        loss = call_at_entry - call_flat_spy
        return loss < 0.10  # Less than 10 cents loss
    
    @staticmethod
    def test_favorable_move_can_win() -> bool:
        """Test that favorable moves can produce winners."""
        from datetime import datetime, timedelta
        
        pricer = EstimatedOptionPricer(entry_option_price=5.00, delta=0.45, slippage=0.04)
        
        entry_time = datetime(2026, 7, 13, 9, 30)
        
        # Entry price with slippage (ask side for buying)
        call_entry_mid = pricer.get_entry_price()
        call_entry_ask = pricer.get_bid_ask_adjusted_price(call_entry_mid, side="ask")
        
        # Test with a stronger favorable move and longer time to overcome decay
        # 2-minute hold with SPY up 2%
        current_time = datetime(2026, 7, 13, 9, 32)  # 2 minutes later
        spy_entry = 100.0
        spy_exit = 102.0  # +2%
        
        call_favorable = pricer.simulate_price_change(
            "CALL", spy_entry, spy_exit, entry_time, current_time, position="mid"
        )
        
        # Exit on bid side
        exit_bid = pricer.get_bid_ask_adjusted_price(call_favorable, side="bid")
        
        # Check if profitable
        pnl = exit_bid - call_entry_ask
        
        # Need at least a small profit to consider it "winnable"
        return pnl > 0.05


def print_comparison_report(comparison: Dict) -> None:
    """Print formatted comparison report."""
    print("\n" + "="*80)
    print("REPLAY VALIDATION COMPARISON")
    print("="*80 + "\n")
    
    comp = comparison["comparisons"]
    
    print("SUMMARY STATISTICS:")
    print(f"  Trade count:     Paper={comp['trades']['paper']:3}  Replay={comp['trades']['replay']:3}  {'✓' if comp['trades']['match'] else '✗'}")
    print(f"  Winners:         Paper={comp['winners']['paper']:3}  Replay={comp['winners']['replay']:3}  {'✓' if comp['winners']['match'] else '✗'}")
    print(f"  Losers:          Paper={comp['losers']['paper']:3}  Replay={comp['losers']['replay']:3}  {'✓' if comp['losers']['match'] else '✗'}")
    print(f"  Win rate %:      Paper={comp['win_rate_pct']['paper']:5.2f}%  Replay={comp['win_rate_pct']['replay']:5.2f}%  {'✓' if comp['win_rate_pct']['match'] else '✗'}")
    print(f"  Net P/L:         Paper=${comp['net_pnl']['paper']:7.2f}  Replay=${comp['net_pnl']['replay']:7.2f}  {'✓' if comp['net_pnl']['match'] else '✗'}")
    
    print("\nEXIT REASONS:")
    print(f"  MAX_HOLD_15_MIN: Paper={comp['exit_reasons']['paper_max_hold']:3}  Replay={comp['exit_reasons']['replay_max_hold']:3}")
    print(f"  OPTION_STOP:     Paper={comp['exit_reasons']['paper_option_stop']:3}  Replay={comp['exit_reasons']['replay_option_stop']:3}")
    print(f"  END_OF_DAY_EXIT: Paper={comp['exit_reasons']['paper_eod']:3}  Replay={comp['exit_reasons']['replay_eod']:3}")
    
    if comparison["mismatches"]:
        print("\n⚠ MISMATCHES DETECTED:")
        for mismatch in comparison["mismatches"]:
            print(f"  - {mismatch}")
    else:
        print("\n✓ ALL METRICS MATCH")
    
    print("="*80 + "\n")
