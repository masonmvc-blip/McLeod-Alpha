"""
Data loader for historical SPY 1-minute OHLCV data.

Validates and cleans CSV data with strict OHLC integrity checks,
timezone conversion to America/New_York, and duplicate removal.
"""

import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path


REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
TIMEZONE = ZoneInfo("America/New_York")


def load_csv_data(csv_path: str) -> pd.DataFrame:
    """
    Load and validate historical SPY 1-minute data from CSV.
    
    Args:
        csv_path: Path to CSV file with OHLCV data
        
    Returns:
        Clean pandas DataFrame with validated OHLC rows, timezone-aware timestamps,
        duplicates removed, and rows sorted chronologically.
        
    Raises:
        FileNotFoundError: CSV file not found
        ValueError: Missing required columns, invalid OHLC, negative volume, etc.
    """
    # Load CSV
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    df = pd.read_csv(csv_path)
    
    # Validate required columns
    validate_columns(df)
    
    # Convert timestamp to datetime with timezone
    df = convert_timestamps(df)
    
    # Remove duplicates (keep first occurrence)
    initial_rows = len(df)
    df = df.drop_duplicates(subset=["timestamp"], keep="first")
    duplicates_removed = initial_rows - len(df)
    if duplicates_removed > 0:
        print(f"Removed {duplicates_removed} duplicate timestamps")
    
    # Validate OHLC and volume
    df = validate_ohlc_rows(df)
    
    # Sort by timestamp
    df = df.sort_values("timestamp").reset_index(drop=True)
    
    print(f"Loaded {len(df)} valid candles from {csv_path}")
    return df


def validate_columns(df: pd.DataFrame) -> None:
    """
    Verify all required columns exist in DataFrame.
    
    Args:
        df: DataFrame to validate
        
    Raises:
        ValueError: If any required column is missing
    """
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(
            f"Missing required columns: {missing}. "
            f"Expected: {REQUIRED_COLUMNS}"
        )


def convert_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse and convert timestamps to America/New_York timezone.
    
    Args:
        df: DataFrame with 'timestamp' column
        
    Returns:
        DataFrame with timezone-aware timestamp column
        
    Raises:
        ValueError: If timestamp parsing fails
    """
    try:
        # Try parsing common datetime formats
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=False)
    except Exception as e:
        raise ValueError(f"Failed to parse timestamp column: {e}")
    
    # Assume UTC if naive, convert to America/New_York
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    
    # Convert to America/New_York
    df["timestamp"] = df["timestamp"].dt.tz_convert(TIMEZONE)
    
    return df


def validate_ohlc_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validate OHLC integrity and volume. Remove invalid rows.
    
    Invalid rows:
    - high < low
    - high < open
    - high < close
    - low > open
    - low > close
    - volume < 0
    
    Args:
        df: DataFrame with OHLC columns
        
    Returns:
        DataFrame with only valid OHLC rows
    """
    initial_rows = len(df)
    
    # Reject high < low
    mask = df["high"] >= df["low"]
    df = df[mask]
    
    # Reject high < open
    mask = df["high"] >= df["open"]
    df = df[mask]
    
    # Reject high < close
    mask = df["high"] >= df["close"]
    df = df[mask]
    
    # Reject low > open
    mask = df["low"] <= df["open"]
    df = df[mask]
    
    # Reject low > close
    mask = df["low"] <= df["close"]
    df = df[mask]
    
    # Reject negative volume
    mask = df["volume"] >= 0
    df = df[mask]
    
    invalid_rows = initial_rows - len(df)
    if invalid_rows > 0:
        print(f"Removed {invalid_rows} invalid OHLC rows")
    
    return df.reset_index(drop=True)


def validate_dataframe(df: pd.DataFrame) -> bool:
    """
    Verify a DataFrame has required structure for replay.
    
    Args:
        df: DataFrame to check
        
    Returns:
        True if valid, False otherwise
    """
    # Check columns
    if not all(col in df.columns for col in REQUIRED_COLUMNS):
        return False
    
    # Check timestamp is timezone-aware
    if df["timestamp"].dt.tz is None:
        return False
    
    # Check sorted
    if not df["timestamp"].is_monotonic_increasing:
        return False
    
    return True


def classify_candle(timestamp) -> str:
    """
    Classify a candle as PREMARKET, REGULAR, or AFTER_HOURS.
    
    Args:
        timestamp: Timezone-aware datetime in America/New_York
        
    Returns:
        "PREMARKET", "REGULAR", or "AFTER_HOURS"
    """
    from datetime import time as dt_time
    
    time_et = timestamp.time()
    market_open = dt_time(9, 30)
    market_close = dt_time(16, 0)
    
    if time_et < market_open:
        return "PREMARKET"
    elif time_et < market_close:
        return "REGULAR"
    else:
        return "AFTER_HOURS"
