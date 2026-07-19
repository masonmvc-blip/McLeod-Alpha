"""
Replay engine for historical candle replay.

Replays completed candles one at a time in chronological order,
exposing only candles available up to the current replay step.
Supports full dataset, date range filtering, and optional premarket inclusion.
"""

import pandas as pd
from datetime import datetime, date
from zoneinfo import ZoneInfo
from typing import Optional, List, Tuple

from backtesting.data_loader import classify_candle, TIMEZONE


class ReplayEngine:
    """
    Historical candle replay engine for backtesting.
    
    Replays candles one at a time, maintaining a window of available
    candles up to the current step. Supports filtering by date range
    and premarket inclusion.
    """
    
    def __init__(
        self,
        df: pd.DataFrame,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        include_premarket: bool = False
    ):
        """
        Initialize replay engine.
        
        Args:
            df: DataFrame from data_loader.load_csv_data()
            start_date: Filter to candles on or after this date (date object)
            end_date: Filter to candles on or before this date (date object)
            include_premarket: Whether to include premarket candles in replay
        """
        self.df = df.copy()
        self.include_premarket = include_premarket
        self.current_step = 0
        
        # Filter by date range
        self.df = self._filter_by_date(start_date, end_date)
        
        # Filter out premarket if not included
        if not include_premarket:
            self.df = self.df[
                self.df["timestamp"].apply(classify_candle) != "PREMARKET"
            ].reset_index(drop=True)
        
        if len(self.df) == 0:
            # Try to provide helpful error message
            candle_types = self.df.apply(
                lambda row: classify_candle(row["timestamp"]), axis=1
            ) if len(self.df) > 0 else []
            raise ValueError(
                f"No candles available after filtering. "
                f"include_premarket={include_premarket}, "
                f"date_range=[{start_date}, {end_date}]"
            )
        
        print(
            f"Replay engine initialized with {len(self.df)} candles "
            f"(premarket included: {include_premarket})"
        )
    
    def _filter_by_date(
        self,
        start_date: Optional[date],
        end_date: Optional[date]
    ) -> pd.DataFrame:
        """
        Filter DataFrame by date range.
        
        Args:
            start_date: Include candles on or after this date
            end_date: Include candles on or before this date
            
        Returns:
            Filtered DataFrame
        """
        result = self.df.copy()
        
        if start_date:
            start_dt = datetime.combine(start_date, datetime.min.time())
            start_dt = start_dt.replace(tzinfo=TIMEZONE)
            result = result[result["timestamp"] >= start_dt]
        
        if end_date:
            # Include entire end_date day
            end_dt = datetime.combine(end_date, datetime.max.time())
            end_dt = end_dt.replace(tzinfo=TIMEZONE)
            result = result[result["timestamp"] <= end_dt]
        
        return result.reset_index(drop=True)
    
    def reset(self) -> None:
        """Reset replay to beginning."""
        self.current_step = 0
    
    def get_candles_up_to_step(self, step: int) -> pd.DataFrame:
        """
        Get all candles available up to a specific step (inclusive).
        
        Args:
            step: Replay step (0-indexed)
            
        Returns:
            DataFrame with candles from step 0 to step
            
        Raises:
            ValueError: If step is out of range
        """
        if step < 0 or step >= len(self.df):
            raise ValueError(
                f"Step {step} out of range [0, {len(self.df)-1}]"
            )
        
        return self.df.iloc[:step+1].copy()
    
    def get_candle_at_step(self, step: int) -> pd.Series:
        """
        Get a single candle at a specific step.
        
        Args:
            step: Replay step (0-indexed)
            
        Returns:
            Series representing the candle
            
        Raises:
            ValueError: If step is out of range
        """
        if step < 0 or step >= len(self.df):
            raise ValueError(
                f"Step {step} out of range [0, {len(self.df)-1}]"
            )
        
        return self.df.iloc[step].copy()
    
    def get_last_candle(self) -> Optional[pd.Series]:
        """
        Get the candle at current_step - 1 (previous candle).
        
        Returns:
            Series representing previous candle, or None if at step 0
        """
        if self.current_step == 0:
            return None
        
        return self.df.iloc[self.current_step - 1].copy()
    
    def next_candle(self) -> Tuple[Optional[pd.Series], str]:
        """
        Move to next candle and return it.
        
        Returns:
            Tuple of (candle, candle_type) where candle_type is one of:
            - "PREMARKET"
            - "REGULAR"
            - "AFTER_HOURS"
            
        Raises:
            StopIteration: If replay is complete
        """
        if self.current_step >= len(self.df):
            raise StopIteration("Replay complete")
        
        candle = self.df.iloc[self.current_step].copy()
        candle_type = classify_candle(candle["timestamp"])
        
        self.current_step += 1
        
        return candle, candle_type
    
    def is_complete(self) -> bool:
        """Check if replay is complete."""
        return self.current_step >= len(self.df)
    
    def total_steps(self) -> int:
        """Get total number of candles to replay."""
        return len(self.df)
    
    def current_candle_number(self) -> int:
        """Get current candle number (1-indexed)."""
        return self.current_step
    
    def get_progress(self) -> Tuple[int, int]:
        """
        Get replay progress.
        
        Returns:
            Tuple of (current_step, total_steps)
        """
        return (self.current_step, len(self.df))
    
    def get_date_range(self) -> Tuple[date, date]:
        """
        Get min and max dates in replay dataset.
        
        Returns:
            Tuple of (start_date, end_date)
        """
        start = self.df["timestamp"].min().date()
        end = self.df["timestamp"].max().date()
        return (start, end)
    
    def verify_no_future_candles(self, step: int) -> bool:
        """
        Verify that no future candles are exposed at a given step.
        
        Args:
            step: Step to check
            
        Returns:
            True if only past candles are exposed
        """
        if step < 0 or step >= len(self.df):
            return False
        
        # All candles up to step should be <= step
        exposed = self.get_candles_up_to_step(step)
        return len(exposed) == step + 1
