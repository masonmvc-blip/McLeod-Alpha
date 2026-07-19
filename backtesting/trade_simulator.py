"""
Historical trade simulator for backtesting.

Converts qualified trading signals from SignalReplayEngine into simulated
trades with entry/exit logic matching production rules.

ENTRY CONSTRAINTS:
- One position open at a time
- Maximum 20 trades per calendar day
- Entries only 9:30 AM - 3:44:59 PM Eastern
- When both CALL and PUT qualify, pick higher score
- Tied scores = no trade

EXIT LOGIC (production-matched):
- Initial stop: -5%
- At +5%: move stop to breakeven
- At +8%: trail 3% below peak
- At +15%: trail 2% below peak
- At +25%: trail 1.5% below peak
- Max hold: 15 minutes
- EOD exit: 3:59 PM Eastern

OUTPUT:
- Simulated trade log (entry/exit times, prices, P&L)
- Summary statistics (win rate, profit factor, etc.)

IMPORTANT: All option prices are ESTIMATED until historical quotes available.
"""

from datetime import datetime, timedelta, time as dt_time
from typing import List, Dict, Tuple, Optional, Any
from zoneinfo import ZoneInfo
import json
import pandas as pd

from backtesting.replay_engine import ReplayEngine
from backtesting.signal_replay import SignalReplayEngine
from backtesting.replay_trade_management import (
    evaluate_trade_management_step,
    initialize_trade_management_state,
)


class SimulatedTrade:
    """Represents a single simulated trade."""
    
    def __init__(
        self,
        entry_time: datetime,
        direction: str,
        spy_entry_price: float,
        option_entry_price: float,
        entry_score: int,
        entry_reasons: List[str],
        feature_snapshot: Dict[str, Any],
        market_regime: str,
        entry_candle_idx: int,
        delta: float = 0.45
    ):
        """Initialize a new simulated trade."""
        self.entry_time = entry_time
        self.direction = direction
        self.spy_entry_price = spy_entry_price
        self.option_entry_price = option_entry_price
        self.entry_score = entry_score
        self.entry_reasons = entry_reasons
        self.feature_snapshot = feature_snapshot
        self.market_regime = market_regime
        self.entry_candle_idx = entry_candle_idx
        self.delta = delta
        
        # Track trade progression
        self.peak_option_price = option_entry_price
        self.peak_option_time = entry_time
        self.current_option_price = option_entry_price
        
        # Match production paper engine: initial option stop is -5% of option entry.
        self.option_stop_level = option_entry_price * (1.0 + TradeSimulator.INITIAL_STOP_PCT)
        self.option_initial_stop = self.option_stop_level
        self.breakeven = False
        self.trailing_threshold = None
        self.management_state = initialize_trade_management_state(
            entry_time=entry_time,
            direction=direction,
            entry_spy_price=spy_entry_price,
            entry_option_price=option_entry_price,
        )
        
        # Track if we've applied entry slippage
        self.entry_slippage_applied = False
        self.exit_slippage_applied = False
        
        # Exit info (filled on exit)
        self.exit_time: Optional[datetime] = None
        self.spy_exit_price: Optional[float] = None
        self.option_exit_price: Optional[float] = None
        self.exit_reason: Optional[str] = None
        self.exit_candle_idx: Optional[int] = None
    
    def to_dict(self, pricing_model: str = "ESTIMATED") -> Dict[str, Any]:
        """Convert trade to dictionary for logging."""
        hold_duration = (
            (self.exit_time - self.entry_time).total_seconds() / 60
            if self.exit_time else 0
        )
        
        if self.option_exit_price and self.option_entry_price:
            dollar_pnl = (self.option_exit_price - self.option_entry_price) * 100
            percent_pnl = (
                (self.option_exit_price - self.option_entry_price) / 
                self.option_entry_price * 100
            )
        else:
            dollar_pnl = 0.0
            percent_pnl = 0.0
        
        return {
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "direction": self.direction,
            "spy_entry_price": round(self.spy_entry_price, 2),
            "spy_exit_price": round(self.spy_exit_price, 2) if self.spy_exit_price else None,
            "option_entry_price": round(self.option_entry_price, 2),
            "option_exit_price": round(self.option_exit_price, 2) if self.option_exit_price else None,
            "quantity": 1,
            "dollar_pnl": round(dollar_pnl, 2),
            "percent_pnl": round(percent_pnl, 2),
            "hold_duration_min": round(hold_duration, 1),
            "entry_score": self.entry_score,
            "entry_reasons": self.entry_reasons,
            "exit_reason": self.exit_reason,
            "market_regime": self.market_regime,
            "momentum_freshness_score": self.feature_snapshot.get("momentum_freshness_score"),
            "momentum_phase": self.feature_snapshot.get("momentum_phase"),
            "pricing_model": pricing_model
        }


class TradeSimulator:
    """Simulates trades from historical signal replay."""
    
    # Market hours (ET)
    MARKET_OPEN = dt_time(9, 30)
    ENTRY_CLOSE = dt_time(15, 44, 59)
    EOD_EXIT = dt_time(15, 59)
    
    # Maximum hold time
    MAX_HOLD_MINUTES = 15
    
        # Stop levels (% move from option entry)
    INITIAL_STOP_PCT = -0.05
    BREAKEVEN_THRESHOLD = 0.05  # At +5%, move to breakeven
    TRAILING_3PCT_THRESHOLD = 0.08  # At +8%, trail 3%
    TRAILING_2PCT_THRESHOLD = 0.15  # At +15%, trail 2%
    TRAILING_1_5PCT_THRESHOLD = 0.25  # At +25%, trail 1.5%
    
    def __init__(
        self,
        replay_engine: ReplayEngine,
        signal_engine: SignalReplayEngine,
        option_pricer: Any,
        max_trades_per_day: int = 20,
        max_hold_minutes: int = 15,
    ):
        """
        Initialize trade simulator.
        
        Args:
            replay_engine: ReplayEngine with historical candles
            signal_engine: SignalReplayEngine with qualified signals
            option_pricer: Option pricing model
            max_trades_per_day: Maximum trades per calendar day
        """
        self.replay_engine = replay_engine
        self.signal_engine = signal_engine
        self.option_pricer = option_pricer
        self.max_trades_per_day = max_trades_per_day
        self.max_hold_minutes = max_hold_minutes
        
        # Replay state
        self.signals: List[Dict[str, Any]] = []
        self.all_candles = pd.DataFrame()
        
        # Trade tracking
        self.trades: List[SimulatedTrade] = []
        self.open_trade: Optional[SimulatedTrade] = None
        self.trades_today = 0
        self.today: Optional[datetime] = None
    
    def run(self) -> List[SimulatedTrade]:
        """
        Run complete backtest simulation.
        
        Returns:
            List of all completed SimulatedTrade objects
        """
        # Get all signals and candles
        self.signals = self.signal_engine.replay()
        self.all_candles = self.replay_engine.get_candles_up_to_step(
            self.replay_engine.total_steps() - 1
        ).copy()
        
        # Reset state
        self.trades = []
        self.open_trade = None
        self.trades_today = 0
        self.today = None
        
        # Process each candle
        for step in range(self.replay_engine.total_steps()):
            candle_row = self.all_candles.iloc[step]
            current_time = pd.to_datetime(candle_row["timestamp"])
            current_time = current_time.tz_convert("America/New_York")
            
            # Check day boundary
            if self.today != current_time.date():
                self.today = current_time.date()
                self.trades_today = 0
            
            # Get signal for this candle (if any)
            signal = self._get_signal_for_step(step)
            
            # Process open trade (exits)
            if self.open_trade:
                self._update_open_trade(step, candle_row, current_time)
            
            # Try to enter new trade
            if not self.open_trade and signal:
                self._try_entry(step, signal, candle_row, current_time)
        
        # Force close any open trade at end
        if self.open_trade:
            self._close_trade("END_OF_DAY_EXIT", None, None)
        
        return self.trades
    
    def _get_signal_for_step(self, step: int) -> Optional[Dict[str, Any]]:
        """Get qualified signal for this step, if any."""
        for sig in self.signals:
            sig_step = sig.get("_step_idx")
            if sig_step == step:
                return sig
        return None
    
    def _try_entry(
        self,
        step: int,
        signal: Dict[str, Any],
        candle_row: pd.Series,
        current_time: datetime
    ) -> None:
        """Try to enter new trade from qualified signal."""
        # Check entry window
        current_et_time = current_time.time()
        if not (self.MARKET_OPEN <= current_et_time <= self.ENTRY_CLOSE):
            return
        
        # Check daily limit
        if self.trades_today >= self.max_trades_per_day:
            return
        
        # Determine direction (CALL or PUT)
        call_qualified = signal.get("call_qualified", False)
        put_qualified = signal.get("put_qualified", False)
        call_score = signal.get("call_score", 0)
        put_score = signal.get("put_score", 0)
        
        # If both qualify, pick higher score
        if call_qualified and put_qualified:
            if call_score > put_score:
                direction = "CALL"
                entry_score = call_score
                entry_reasons = signal.get("call_reasons", [])
                momentum_score = signal.get("momentum_freshness_score_call")
                momentum_phase = signal.get("momentum_phase_call", "MID")
            elif put_score > call_score:
                direction = "PUT"
                entry_score = put_score
                entry_reasons = signal.get("put_reasons", [])
                momentum_score = signal.get("momentum_freshness_score_put")
                momentum_phase = signal.get("momentum_phase_put", "MID")
            else:
                # Tie - no trade
                return
        elif call_qualified:
            direction = "CALL"
            entry_score = call_score
            entry_reasons = signal.get("call_reasons", [])
            momentum_score = signal.get("momentum_freshness_score_call")
            momentum_phase = signal.get("momentum_phase_call", "MID")
        elif put_qualified:
            direction = "PUT"
            entry_score = put_score
            entry_reasons = signal.get("put_reasons", [])
            momentum_score = signal.get("momentum_freshness_score_put")
            momentum_phase = signal.get("momentum_phase_put", "MID")
        else:
            return
        
        # Create trade
        spy_entry_price = float(candle_row["close"])
        # Match production paper_engine: entry uses option mark directly.
        if hasattr(self.option_pricer, "get_entry_price"):
            try:
                option_mid_price = self.option_pricer.get_entry_price(
                    direction=direction,
                    entry_time=current_time,
                    entry_spy_price=spy_entry_price,
                )
            except TypeError:
                option_mid_price = self.option_pricer.get_entry_price()
        else:
            raise ValueError("Option pricer must provide get_entry_price()")
        option_entry_price = option_mid_price
        
        feature_snapshot = {
            "support_resistance": signal.get("support_resistance", {}),
            "macd_data": signal.get("macd_data", {}),
            "volume_trend": signal.get("volume_trend", "UNKNOWN"),
            "momentum_freshness_score": momentum_score,
            "momentum_phase": momentum_phase,
        }
        
        self.open_trade = SimulatedTrade(
            entry_time=current_time,
            direction=direction,
            spy_entry_price=spy_entry_price,
            option_entry_price=option_entry_price,
            entry_score=entry_score,
            entry_reasons=entry_reasons,
            feature_snapshot=feature_snapshot,
            market_regime=signal.get("market_regime", "NO_TRADE"),
            entry_candle_idx=step,
            delta=self.option_pricer.delta
        )
        
        self.trades_today += 1
    
    def _update_open_trade(
        self,
        step: int,
        candle_row: pd.Series,
        current_time: datetime
    ) -> None:
        """Update open trade, check for exits."""
        if not self.open_trade:
            return
        
        current_spy_price = float(candle_row["close"])
        result = evaluate_trade_management_step(
            state=self.open_trade.management_state,
            pricer=self.option_pricer,
            current_spy_price=current_spy_price,
            current_time=current_time,
            eod_exit_time=self.EOD_EXIT,
            max_hold_minutes=self.max_hold_minutes,
        )

        self.open_trade.current_option_price = result.option_mark
        self.open_trade.peak_option_price = self.open_trade.management_state.peak_option_price
        self.open_trade.breakeven = self.open_trade.management_state.breakeven_armed
        self.open_trade.option_stop_level = self.open_trade.management_state.active_stop
        self.open_trade.option_initial_stop = self.open_trade.management_state.initial_stop

        if result.exit_decision == "EXIT":
            self._close_trade(result.exit_reason, step, current_time, result.final_option_price)
            return
    
    def _close_trade(
        self,
        exit_reason: str,
        exit_step: Optional[int],
        exit_time: Optional[datetime],
        option_exit_price: Optional[float] = None,
    ) -> None:
        """Close the open trade."""
        if not self.open_trade:
            return
        
        # Use current option price or calculate from last candle
        self.open_trade.exit_reason = exit_reason
        self.open_trade.exit_candle_idx = exit_step
        self.open_trade.exit_time = exit_time
        
        # Production parity: manage_trade passes the execution quote directly to close_trade.
        if option_exit_price is None:
            option_exit_price = self.open_trade.current_option_price
        self.open_trade.option_exit_price = option_exit_price
        
        # Exit SPY price (use the current close, not stop level)
        self.open_trade.spy_exit_price = self.open_trade.spy_entry_price
        
        # Add to trades list
        self.trades.append(self.open_trade)
        self.open_trade = None
    
    def get_trades_dataframe(self) -> pd.DataFrame:
        """Convert trades to DataFrame."""
        records = [t.to_dict(self.option_pricer.MODEL_NAME) for t in self.trades]
        return pd.DataFrame(records)
    
    def get_summary(self) -> Dict[str, Any]:
        """Generate summary statistics."""
        if not self.trades:
            return {
                "total_trades": 0,
                "winners": 0,
                "losers": 0,
                "win_rate_pct": 0.0,
                "net_pnl": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "avg_winner": 0.0,
                "avg_loser": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "max_drawdown": 0.0,
                "call_trades": 0,
                "put_trades": 0,
                "call_winners": 0,
                "put_winners": 0,
                "by_score": {},
                "by_exit_reason": {},
                "by_hour": {},
                "by_regime": {},
                "by_momentum_phase": {}
            }
        
        # Calculate basic stats
        total = len(self.trades)
        winners = len([t for t in self.trades if t.to_dict()["dollar_pnl"] > 0])
        losers = len([t for t in self.trades if t.to_dict()["dollar_pnl"] < 0])
        win_rate = (winners / total * 100) if total > 0 else 0.0
        
        # Calculate P&L
        pnls = [t.to_dict()["dollar_pnl"] for t in self.trades]
        net_pnl = sum(pnls)
        gross_profit = sum([p for p in pnls if p > 0])
        gross_loss = sum([abs(p) for p in pnls if p < 0])
        avg_winner = (gross_profit / winners) if winners > 0 else 0.0
        avg_loser = (gross_loss / losers) if losers > 0 else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0 if gross_profit == 0 else float('inf')
        expectancy = (net_pnl / total) if total > 0 else 0.0
        
        # Calculate max drawdown (simple peak-to-trough)
        cumulative = 0
        peak = 0
        max_dd = 0
        for pnl in pnls:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        
        # By direction
        call_trades = len([t for t in self.trades if t.direction == "CALL"])
        put_trades = len([t for t in self.trades if t.direction == "PUT"])
        call_winners = len([t for t in self.trades if t.direction == "CALL" and t.to_dict()["dollar_pnl"] > 0])
        put_winners = len([t for t in self.trades if t.direction == "PUT" and t.to_dict()["dollar_pnl"] > 0])
        
        # By entry score
        by_score = {}
        for t in self.trades:
            score = t.entry_score
            if score not in by_score:
                by_score[score] = {"count": 0, "wins": 0, "pnl": 0.0}
            by_score[score]["count"] += 1
            by_score[score]["pnl"] += t.to_dict()["dollar_pnl"]
            if t.to_dict()["dollar_pnl"] > 0:
                by_score[score]["wins"] += 1
        
        # By exit reason
        by_exit = {}
        for t in self.trades:
            reason = t.exit_reason
            if reason not in by_exit:
                by_exit[reason] = {"count": 0, "wins": 0, "pnl": 0.0}
            by_exit[reason]["count"] += 1
            by_exit[reason]["pnl"] += t.to_dict()["dollar_pnl"]
            if t.to_dict()["dollar_pnl"] > 0:
                by_exit[reason]["wins"] += 1
        
        # By hour
        by_hour = {}
        for t in self.trades:
            hour = t.entry_time.strftime("%H:00")
            if hour not in by_hour:
                by_hour[hour] = {"count": 0, "wins": 0, "pnl": 0.0}
            by_hour[hour]["count"] += 1
            by_hour[hour]["pnl"] += t.to_dict()["dollar_pnl"]
            if t.to_dict()["dollar_pnl"] > 0:
                by_hour[hour]["wins"] += 1
        
        # By regime
        by_regime = {}
        for t in self.trades:
            regime = t.market_regime
            if regime not in by_regime:
                by_regime[regime] = {"count": 0, "wins": 0, "pnl": 0.0}
            by_regime[regime]["count"] += 1
            by_regime[regime]["pnl"] += t.to_dict()["dollar_pnl"]
            if t.to_dict()["dollar_pnl"] > 0:
                by_regime[regime]["wins"] += 1

        # By momentum phase
        by_momentum_phase = {}
        for t in self.trades:
            phase = str(t.feature_snapshot.get("momentum_phase") or "UNKNOWN")
            if phase not in by_momentum_phase:
                by_momentum_phase[phase] = {"count": 0, "wins": 0, "pnl": 0.0}
            by_momentum_phase[phase]["count"] += 1
            by_momentum_phase[phase]["pnl"] += t.to_dict()["dollar_pnl"]
            if t.to_dict()["dollar_pnl"] > 0:
                by_momentum_phase[phase]["wins"] += 1
        
        return {
            "total_trades": total,
            "winners": winners,
            "losers": losers,
            "win_rate_pct": round(win_rate, 2),
            "net_pnl": round(net_pnl, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "avg_winner": round(avg_winner, 2),
            "avg_loser": round(avg_loser, 2),
            "profit_factor": round(profit_factor, 2),
            "expectancy": round(expectancy, 2),
            "max_drawdown": round(max_dd, 2),
            "call_trades": call_trades,
            "put_trades": put_trades,
            "call_winners": call_winners,
            "put_winners": put_winners,
            "by_score": {str(k): v for k, v in by_score.items()},
            "by_exit_reason": by_exit,
            "by_hour": by_hour,
            "by_regime": by_regime,
            "by_momentum_phase": by_momentum_phase,
            "pricing_model": self.option_pricer.MODEL_NAME
        }
