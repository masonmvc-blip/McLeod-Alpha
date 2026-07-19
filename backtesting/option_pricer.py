"""
Simulated option pricing model for backtesting.

This module provides synthetic option price calculations when historical
option quotes are unavailable. All results are clearly labeled ESTIMATED.

When real historical option data becomes available, this model can be
replaced with actual quotes while maintaining the same interface.

PRICING MODEL:
- Entry price: Configurable (default $5.00)
- Delta: Configurable (default 0.45)
- CALL follows positive SPY moves, PUT follows negative
- Time decay: Applied linearly based on hold duration
- Bid/ask slippage: Applied symmetrically (default $0.04)
- Floor: Never below $0.01

IMPORTANT: All prices returned are ESTIMATED. Use real option quotes
when available to replace this synthetic model.
"""

from datetime import datetime, timedelta
from typing import Tuple, Dict, Any
import math


class EstimatedOptionPricer:
    """Simulated option pricer for backtesting without historical quotes."""
    
    MODEL_NAME = "ESTIMATED"  # Label for all outputs
    
    def __init__(
        self,
        entry_option_price: float = 5.00,
        delta: float = 0.45,
        time_decay_per_minute: float = 0.02,
        slippage: float = 0.04,
        floor: float = 0.01
    ):
        """
        Initialize option pricer.
        
        Args:
            entry_option_price: Starting option price in dollars
            delta: Sensitivity to underlying move (0-1), default 0.45 (realistic)
            time_decay_per_minute: Theta per minute ($), default 0.02
            slippage: Bid/ask spread in dollars, default 0.04
            floor: Minimum option price, default $0.01 (prevents negative)
        """
        self.entry_option_price = entry_option_price
        self.delta = delta
        self.time_decay_per_minute = time_decay_per_minute
        self.slippage = slippage
        self.floor = floor
    
    def get_entry_price(self) -> float:
        """Get initial option price at entry."""
        return max(self.entry_option_price, self.floor)
    
    def simulate_price_change(
        self,
        direction: str,
        entry_spy_price: float,
        current_spy_price: float,
        entry_time: datetime,
        current_time: datetime,
        position: str = "entry"
    ) -> float:
        """
        Simulate option price at given SPY price and time.
        
        CORRECTED FORMULA:
        - CALL option change = delta * (current_spy_price - entry_spy_price)
        - PUT option change = delta * (entry_spy_price - current_spy_price)
        
        Delta is applied to DOLLAR change in SPY, not percentage change.
        Example: SPY 750→751 ($1 move), delta 0.45 → option +$0.45
        NOT: percentage 0.133% * 0.45 = 0.06% change
        
        Args:
            direction: "CALL" or "PUT"
            entry_spy_price: SPY price at entry
            current_spy_price: SPY price at current time
            entry_time: Timestamp when position opened
            current_time: Current timestamp
            position: "entry" (no time decay) or "mid" (apply time decay)
        
        Returns:
            Estimated option price (never below floor)
        """
        # Calculate SPY movement in DOLLARS (not percentage!)
        spy_move_dollars = current_spy_price - entry_spy_price
        
        # Calculate time elapsed (minutes)
        time_elapsed = (current_time - entry_time).total_seconds() / 60.0
        
        # Base option price movement using DOLLAR DELTA
        if direction == "CALL":
            # CALL benefits from positive SPY move (up $1 → option +$delta)
            option_move = spy_move_dollars * self.delta
        elif direction == "PUT":
            # PUT benefits from negative SPY move (down $1 → option +$delta)
            option_move = -spy_move_dollars * self.delta
        else:
            raise ValueError(f"Invalid direction: {direction}")
        
        # Apply delta-based move to entry price
        current_price = self.entry_option_price + option_move
        
        # Apply time decay (theta) if not at entry
        if position != "entry":
            time_decay = self.time_decay_per_minute * time_elapsed
            current_price -= time_decay
        
        # Floor to prevent negative prices
        current_price = max(current_price, self.floor)
        
        return current_price
    
    def get_bid_ask_adjusted_price(
        self,
        mid_price: float,
        side: str = "ask"
    ) -> float:
        """
        Apply bid/ask spread to mid price.
        
        Args:
            mid_price: Mid-market price
            side: "bid" (lower) or "ask" (higher)
        
        Returns:
            Price with slippage applied
        """
        if side == "bid":
            return max(mid_price - self.slippage / 2, self.floor)
        elif side == "ask":
            return max(mid_price + self.slippage / 2, self.floor)
        else:
            raise ValueError(f"Invalid side: {side}")
    
    def calculate_pnl(
        self,
        direction: str,
        entry_price: float,
        exit_price: float,
        quantity: int = 1
    ) -> Tuple[float, float]:
        """
        Calculate P&L for simulated trade.
        
        Args:
            direction: "CALL" or "PUT"
            entry_price: Entry option price
            exit_price: Exit option price
            quantity: Number of contracts
        
        Returns:
            (dollar_pnl, percent_pnl) tuple
        """
        if entry_price <= 0:
            return 0.0, 0.0
        
        # Option P&L: (exit - entry) * 100 * quantity
        # (100 shares per contract)
        dollar_pnl = (exit_price - entry_price) * 100 * quantity
        percent_pnl = ((exit_price - entry_price) / entry_price) * 100
        
        return dollar_pnl, percent_pnl
    
    def get_info_dict(self) -> Dict[str, Any]:
        """Get configuration info for logging."""
        return {
            "model": self.MODEL_NAME,
            "entry_price": self.entry_option_price,
            "delta": self.delta,
            "time_decay_per_minute": self.time_decay_per_minute,
            "slippage": self.slippage,
            "floor": self.floor,
            "note": "All prices are ESTIMATED. Use real option quotes when available."
        }


class HistoricalOptionPricer:
    """
    Placeholder for real historical option pricer.
    
    When historical option quotes are available (e.g., from API, CSV),
    replace this stub with actual implementation and swap EstimatedOptionPricer
    for HistoricalOptionPricer in trade_simulator.py.
    """
    
    MODEL_NAME = "HISTORICAL"
    
    def __init__(self):
        raise NotImplementedError(
            "Historical option pricing not yet implemented. "
            "Use EstimatedOptionPricer for now."
        )
