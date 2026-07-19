"""
Strategy optimization and comparison engine for backtesting.

Runs multiple backtests with different parameter combinations and produces
ranked summaries for comparison.

DEFAULTS:
- Call thresholds: 4, 5, 6
- Put thresholds: 4, 5, 6
- Max hold times: 10, 15, 20 minutes
- Max trades per day: 20
- Total combinations: 3 * 3 * 3 = 27 default backtests
"""

from typing import List, Dict, Tuple, Any
from pathlib import Path
from datetime import datetime
import pandas as pd
import json

from backtesting import load_csv_data, ReplayEngine
from backtesting.signal_replay import SignalReplayEngine
from backtesting.historical_option_playback import build_replay_option_pricer
from backtesting.trade_simulator import TradeSimulator


class StrategyParameters:
    """Encapsulates a single parameter combination."""
    
    def __init__(
        self,
        call_threshold: int = 5,
        put_threshold: int = 5,
        max_hold_minutes: int = 15,
        max_trades_per_day: int = 20
    ):
        self.call_threshold = call_threshold
        self.put_threshold = put_threshold
        self.max_hold_minutes = max_hold_minutes
        self.max_trades_per_day = max_trades_per_day
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "call_threshold": self.call_threshold,
            "put_threshold": self.put_threshold,
            "max_hold_minutes": self.max_hold_minutes,
            "max_trades_per_day": self.max_trades_per_day
        }
    
    def __eq__(self, other):
        if not isinstance(other, StrategyParameters):
            return False
        return self.to_dict() == other.to_dict()
    
    def __hash__(self):
        return hash((
            self.call_threshold,
            self.put_threshold,
            self.max_hold_minutes,
            self.max_trades_per_day
        ))
    
    def __repr__(self):
        return (f"Call:{self.call_threshold} Put:{self.put_threshold} "
                f"Hold:{self.max_hold_minutes}m Trades:{self.max_trades_per_day}")


class StrategyResult:
    """Represents the backtest result for one parameter combination."""
    
    def __init__(
        self,
        parameters: StrategyParameters,
        summary: Dict[str, Any],
        trades: List[Dict[str, Any]]
    ):
        self.parameters = parameters
        self.summary = summary
        self.trades = trades
    
    def to_row(self) -> Dict[str, Any]:
        """Convert to CSV row format."""
        row = {
            "call_threshold": self.parameters.call_threshold,
            "put_threshold": self.parameters.put_threshold,
            "max_hold_minutes": self.parameters.max_hold_minutes,
            "max_trades_per_day": self.parameters.max_trades_per_day,
            "total_trades": self.summary.get("total_trades", 0),
            "winners": self.summary.get("winners", 0),
            "losers": self.summary.get("losers", 0),
            "win_rate_pct": self.summary.get("win_rate_pct", 0.0),
            "net_pnl": self.summary.get("net_pnl", 0.0),
            "gross_profit": self.summary.get("gross_profit", 0.0),
            "gross_loss": self.summary.get("gross_loss", 0.0),
            "avg_winner": self.summary.get("avg_winner", 0.0),
            "avg_loser": self.summary.get("avg_loser", 0.0),
            "profit_factor": self.summary.get("profit_factor", 0.0),
            "expectancy": self.summary.get("expectancy", 0.0),
            "max_drawdown": self.summary.get("max_drawdown", 0.0),
            "call_trades": self.summary.get("call_trades", 0),
            "put_trades": self.summary.get("put_trades", 0),
            "call_winners": self.summary.get("call_winners", 0),
            "put_winners": self.summary.get("put_winners", 0),
        }
        return row


class StrategyOptimizer:
    """Runs multiple backtests and compares results."""
    
    def __init__(
        self,
        csv_path: str,
        call_thresholds: List[int] = None,
        put_thresholds: List[int] = None,
        max_hold_times: List[int] = None,
        max_trades_per_day: int = 20,
        date_from: str = None,
        date_to: str = None,
        include_premarket: bool = False,
        delta: float = 0.45,
        entry_option_price: float = 5.00,
        slippage: float = 0.04
    ):
        """
        Initialize strategy optimizer.
        
        Args:
            csv_path: Path to historical OHLCV CSV
            call_thresholds: List of call thresholds to test (default [4, 5, 6])
            put_thresholds: List of put thresholds to test (default [4, 5, 6])
            max_hold_times: List of max hold times in minutes (default [10, 15, 20])
            max_trades_per_day: Fixed trades per day limit
            date_from: Start date (optional)
            date_to: End date (optional)
            include_premarket: Include premarket candles
            delta: Option delta
            entry_option_price: Entry option price
            slippage: Bid/ask slippage
        """
        self.csv_path = csv_path
        self.call_thresholds = call_thresholds or [4, 5, 6]
        self.put_thresholds = put_thresholds or [4, 5, 6]
        self.max_hold_times = max_hold_times or [10, 15, 20]
        self.max_trades_per_day = max_trades_per_day
        self.date_from = date_from
        self.date_to = date_to
        self.include_premarket = include_premarket
        self.delta = delta
        self.entry_option_price = entry_option_price
        self.slippage = slippage
        
        # Load data once (reuse across all backtests)
        self.df = load_csv_data(csv_path)
        
        # Results storage
        self.results: List[StrategyResult] = []
    
    def run_all(self) -> List[StrategyResult]:
        """
        Run all parameter combination backtests.
        
        Returns:
            List of StrategyResult objects, sorted by profit factor (descending)
        """
        self.results = []
        total_combos = (
            len(self.call_thresholds) *
            len(self.put_thresholds) *
            len(self.max_hold_times)
        )
        
        print(f"\nRunning {total_combos} backtest combinations...")
        current = 0
        
        for call_thresh in self.call_thresholds:
            for put_thresh in self.put_thresholds:
                for max_hold in self.max_hold_times:
                    current += 1
                    params = StrategyParameters(
                        call_threshold=call_thresh,
                        put_threshold=put_thresh,
                        max_hold_minutes=max_hold,
                        max_trades_per_day=self.max_trades_per_day
                    )
                    
                    print(f"  [{current}/{total_combos}] Testing {params}...", end="")
                    
                    try:
                        result = self._run_single_backtest(params)
                        self.results.append(result)
                        print(f" ✓ ({result.summary['total_trades']} trades, "
                              f"${result.summary['net_pnl']:.2f} P/L)")
                    except Exception as e:
                        print(f" ✗ ERROR: {e}")
        
        # Sort by profit factor (descending), then by expectancy
        self.results.sort(
            key=lambda r: (
                -r.summary.get("profit_factor", 0),
                -r.summary.get("expectancy", 0),
                -r.summary.get("net_pnl", 0)
            )
        )
        
        return self.results
    
    def _run_single_backtest(self, params: StrategyParameters) -> StrategyResult:
        """Run a single backtest with given parameters."""
        # Create fresh replay engines
        replay_engine = ReplayEngine(
            self.df.copy(),
            start_date=self.date_from,
            end_date=self.date_to,
            include_premarket=self.include_premarket
        )
        
        signal_engine = SignalReplayEngine(
            replay_engine,
            call_threshold=params.call_threshold,
            put_threshold=params.put_threshold
        )
        
        option_pricer = build_replay_option_pricer(
            entry_option_price=self.entry_option_price,
            delta=self.delta,
            slippage=self.slippage,
            trade_date=self.date_from if self.date_from == self.date_to else None,
        )
        
        simulator = TradeSimulator(
            replay_engine=replay_engine,
            signal_engine=signal_engine,
            option_pricer=option_pricer,
            max_trades_per_day=params.max_trades_per_day
        )
        
        # Run simulation
        trades = simulator.run()
        summary = simulator.get_summary()
        
        # Convert trades to dict format
        trades_list = [t.to_dict() for t in trades]
        
        return StrategyResult(params, summary, trades_list)
    
    def get_comparison_dataframe(self) -> pd.DataFrame:
        """Get results as DataFrame for CSV export."""
        rows = [r.to_row() for r in self.results]
        return pd.DataFrame(rows)
    
    def get_top_results(self, n: int = 10) -> List[Tuple[StrategyParameters, Dict[str, Any]]]:
        """
        Get top N parameter combinations by profit factor.
        
        Returns:
            List of (StrategyParameters, summary_dict) tuples
        """
        return [(r.parameters, r.summary) for r in self.results[:n]]
    
    def print_comparison_table(self, n: int = 10):
        """Print formatted comparison table."""
        print("\n" + "="*120)
        print("TOP PARAMETER COMBINATIONS (sorted by Profit Factor, Expectancy, Net P/L)")
        print("="*120)
        
        # Header
        print(f"{'Rank':<6} {'Call':>4} {'Put':>4} {'Hold':>5} {'Trades':>7} {'W-L':>8} "
              f"{'WR%':>6} {'NetP/L':>10} {'ProfFac':>8} {'Expect':>8} {'MaxDD':>8}")
        print("-"*120)
        
        for i, result in enumerate(self.results[:n], 1):
            p = result.parameters
            s = result.summary
            
            w_l = f"{s.get('winners', 0)}-{s.get('losers', 0)}"
            
            print(f"{i:<6} {p.call_threshold:>4} {p.put_threshold:>4} "
                  f"{p.max_hold_minutes:>5} {s.get('total_trades', 0):>7} {w_l:>8} "
                  f"{s.get('win_rate_pct', 0):>5.1f}% ${s.get('net_pnl', 0):>9.2f} "
                  f"{s.get('profit_factor', 0):>8.2f} ${s.get('expectancy', 0):>7.2f} "
                  f"${s.get('max_drawdown', 0):>7.2f}")
        
        print("="*120 + "\n")
    
    def get_summary_json(self) -> Dict[str, Any]:
        """Get optimization summary as JSON-serializable dict."""
        return {
            "optimization_run": datetime.now().isoformat(),
            "total_combinations": len(self.results),
            "call_thresholds_tested": self.call_thresholds,
            "put_thresholds_tested": self.put_thresholds,
            "max_hold_times_tested": self.max_hold_times,
            "max_trades_per_day": self.max_trades_per_day,
            "top_10_results": [
                {
                    "rank": i + 1,
                    "parameters": r.parameters.to_dict(),
                    "summary": {
                        "total_trades": r.summary.get("total_trades", 0),
                        "winners": r.summary.get("winners", 0),
                        "losers": r.summary.get("losers", 0),
                        "win_rate_pct": r.summary.get("win_rate_pct", 0.0),
                        "net_pnl": r.summary.get("net_pnl", 0.0),
                        "gross_profit": r.summary.get("gross_profit", 0.0),
                        "gross_loss": r.summary.get("gross_loss", 0.0),
                        "avg_winner": r.summary.get("avg_winner", 0.0),
                        "avg_loser": r.summary.get("avg_loser", 0.0),
                        "profit_factor": r.summary.get("profit_factor", 0.0),
                        "expectancy": r.summary.get("expectancy", 0.0),
                        "max_drawdown": r.summary.get("max_drawdown", 0.0),
                        "call_trades": r.summary.get("call_trades", 0),
                        "put_trades": r.summary.get("put_trades", 0),
                        "call_winners": r.summary.get("call_winners", 0),
                        "put_winners": r.summary.get("put_winners", 0),
                    }
                }
                for i, r in enumerate(self.results[:10])
            ]
        }
