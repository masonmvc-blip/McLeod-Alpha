"""
Pure trading signal calculation functions.

These functions are extracted from phase3_monitor.py to enable
reuse in both live trading and historical backtesting.

All functions are deterministic and have no side effects.
"""

import pandas as pd
import math
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo


REGIME_VWAP_TOLERANCE_PCT = 0.0025


def add_indicators(df):
    """
    Add technical indicators to OHLCV DataFrame.
    
    Adds: EMA10, EMA20, EMA50, VWAP, MACD, MACD Signal, MACD Histogram
    
    Args:
        df: DataFrame with datetime, close, high, low, volume columns
        
    Returns:
        DataFrame with indicators added
    """
    df = df.copy()
    df["ema10"] = df["close"].ewm(span=10, adjust=False).mean()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    typical = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (typical * df["volume"]).cumsum() / df["volume"].cumsum()

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    df["macd"] = macd
    df["macd_signal"] = signal
    df["macd_hist"] = macd - signal

    return df


def calculate_fibonacci_levels(swing_high, swing_low, price):
    """
    Calculate Fibonacci retracement and extension levels.
    
    Args:
        swing_high: Recent swing high price
        swing_low: Recent swing low price
        price: Current price
        
    Returns:
        Dict with Fibonacci retracement and extension levels
    """
    if swing_high is None or swing_low is None:
        return {}
    
    move_distance = swing_high - swing_low
    
    if move_distance <= 0:
        return {}
    
    # Standard Fibonacci retracement levels (from high to low)
    fib_ratios = {
        "0.0": 0.0,
        "23.6": 0.236,
        "38.2": 0.382,
        "50.0": 0.5,
        "61.8": 0.618,
        "78.6": 0.786,
        "100.0": 1.0,
    }
    
    # Fibonacci extension levels (beyond 100%)
    extension_ratios = {
        "127.2": 1.272,
        "161.8": 1.618,
        "200.0": 2.0,
        "261.8": 2.618,
    }
    
    retracement_levels = {}
    for level_name, ratio in fib_ratios.items():
        level_price = swing_high - (move_distance * ratio)
        retracement_levels[f"fib_{level_name}"] = float(level_price)
    
    extension_levels = {}
    for level_name, ratio in extension_ratios.items():
        level_price = swing_high + (move_distance * (ratio - 1.0))
        extension_levels[f"fib_ext_{level_name}"] = float(level_price)
    
    # Find nearest retracement level to current price
    retracement_prices = list(retracement_levels.values())
    nearest_retracement = None
    if price <= swing_high and price >= swing_low:
        # Price is within the swing range
        above_price = [p for p in retracement_prices if p >= price]
        below_price = [p for p in retracement_prices if p <= price]
        if above_price and below_price:
            above_nearest = min(above_price)
            below_nearest = max(below_price)
            nearest_retracement = above_nearest if abs(above_nearest - price) < abs(below_nearest - price) else below_nearest
        elif above_price:
            nearest_retracement = min(above_price)
        elif below_price:
            nearest_retracement = max(below_price)
    
    return {
        "swing_high": float(swing_high),
        "swing_low": float(swing_low),
        "move_distance": float(move_distance),
        "retracement_levels": retracement_levels,
        "extension_levels": extension_levels,
        "nearest_retracement_level": nearest_retracement,
    }


def build_feature_snapshot(df, *, exclude_last_candle=True):
    """
    Build support/resistance and MACD analysis snapshot.
    
    Args:
        df: DataFrame with complete indicators (EMA, VWAP, MACD)
        exclude_last_candle: Whether the final row may be an incomplete candle.
        
    Returns:
        Dict with support_resistance and macd data
    """
    if df is None or df.empty:
        return {}

    completed_df = df.iloc[:-1].copy() if exclude_last_candle and len(df) > 1 else df.copy()
    if completed_df.empty:
        return {}

    current_row = completed_df.iloc[-1]
    prev_row = completed_df.iloc[-2] if len(completed_df) > 1 else current_row
    price = float(current_row.get("close", 0.0) or 0.0)

    half_dollar_support = math.floor(price * 2.0) / 2.0
    half_dollar_resistance = math.ceil(price * 2.0) / 2.0
    whole_dollar_support = math.floor(price)
    whole_dollar_resistance = math.ceil(price)

    if "timestamp" in completed_df.columns:
        # Assume timestamp is already timezone-aware
        if completed_df["timestamp"].dt.tz is None:
            completed_df["timestamp"] = pd.to_datetime(completed_df["timestamp"], utc=True)
        completed_df_tz = completed_df["timestamp"].dt.tz_convert("America/New_York")
    elif "datetime" in completed_df.columns:
        completed_df_tz = pd.to_datetime(completed_df["datetime"], utc=True).dt.tz_convert("America/New_York")
    else:
        return {}

    current_date = completed_df_tz.iloc[-1].date()
    current_day_rows = completed_df[completed_df_tz.dt.date == current_date]
    previous_day_rows = completed_df[completed_df_tz.dt.date == (current_date - timedelta(days=1))]

    prior_day_high = float(previous_day_rows["high"].max()) if not previous_day_rows.empty else None
    prior_day_low = float(previous_day_rows["low"].min()) if not previous_day_rows.empty else None

    premarket_rows = current_day_rows[completed_df_tz[completed_df_tz.dt.date == current_date].dt.time < dt_time(9, 30)]
    premarket_high = float(premarket_rows["high"].max()) if not premarket_rows.empty else None
    premarket_low = float(premarket_rows["low"].min()) if not premarket_rows.empty else None

    recent_rows = completed_df.tail(20).copy()
    swing_highs = []
    swing_lows = []
    if len(recent_rows) >= 3:
        for idx in range(1, len(recent_rows) - 1):
            current_row_loop = recent_rows.iloc[idx]
            prev_row_loop = recent_rows.iloc[idx - 1]
            next_row_loop = recent_rows.iloc[idx + 1]
            if float(current_row_loop["high"]) > float(prev_row_loop["high"]) and float(current_row_loop["high"]) >= float(next_row_loop["high"]):
                swing_highs.append(float(current_row_loop["high"]))
            if float(current_row_loop["low"]) < float(prev_row_loop["low"]) and float(current_row_loop["low"]) <= float(next_row_loop["low"]):
                swing_lows.append(float(current_row_loop["low"]))

    nearest_swing_high = swing_highs[-1] if swing_highs else None
    nearest_swing_low = swing_lows[-1] if swing_lows else None

    resistance_candidates = [value for value in [prior_day_high, premarket_high, nearest_swing_high] if value is not None]
    support_candidates = [value for value in [prior_day_low, premarket_low, nearest_swing_low] if value is not None]

    if resistance_candidates:
        above_resistance = [value for value in resistance_candidates if value > price]
        nearest_resistance = min(above_resistance) if above_resistance else max(resistance_candidates)
    else:
        nearest_resistance = None

    if support_candidates:
        below_support = [value for value in support_candidates if value < price]
        nearest_support = max(below_support) if below_support else min(support_candidates)
    else:
        nearest_support = None

    distance_to_resistance = (nearest_resistance - price) if nearest_resistance is not None else None
    distance_to_support = (price - nearest_support) if nearest_support is not None else None
    distance_to_resistance_pct = (distance_to_resistance / price * 100) if nearest_resistance is not None and price else None
    distance_to_support_pct = (distance_to_support / price * 100) if nearest_support is not None and price else None

    close_above_resistance = bool(price > nearest_resistance) if nearest_resistance is not None else False
    close_below_support = bool(price < nearest_support) if nearest_support is not None else False

    if len(completed_df) >= 6:
        recent_volume = completed_df.iloc[-6:-1]["volume"].astype(float)
        avg_recent_volume = float(recent_volume.mean()) if not recent_volume.empty else 0.0
    else:
        avg_recent_volume = 0.0

    current_volume = float(current_row.get("volume", 0) or 0.0)
    breakout_confirmation = bool(close_above_resistance and current_volume > avg_recent_volume)
    breakdown_confirmation = bool(close_below_support and current_volume > avg_recent_volume)

    if "macd" not in completed_df.columns:
        completed_df["macd"] = 0.0
    if "macd_signal" not in completed_df.columns:
        completed_df["macd_signal"] = 0.0
    if "macd_hist" not in completed_df.columns:
        completed_df["macd_hist"] = 0.0

    macd_series = completed_df["macd"].astype(float)
    signal_series = completed_df["macd_signal"].astype(float)
    bullish_crossover = False
    bearish_crossover = False
    if len(macd_series) >= 2:
        recent_pairs = list(zip(macd_series.iloc[-3:].tolist(), signal_series.iloc[-3:].tolist()))
        for index in range(1, len(recent_pairs)):
            prev_macd, prev_signal = recent_pairs[index - 1]
            curr_macd, curr_signal = recent_pairs[index]
            if prev_macd <= prev_signal and curr_macd > curr_signal:
                bullish_crossover = True
            if prev_macd >= prev_signal and curr_macd < curr_signal:
                bearish_crossover = True

    current_macd = float(current_row.get("macd", 0.0) or 0.0)
    current_signal = float(current_row.get("macd_signal", 0.0) or 0.0)
    current_hist = float(current_row.get("macd_hist", 0.0) or 0.0)
    prev_hist = float(prev_row.get("macd_hist", 0.0) or 0.0)
    histogram_direction = "STRENGTHENING" if current_hist > prev_hist else "WEAKENING" if current_hist < prev_hist else "NEUTRAL"

    # Calculate Fibonacci levels based on recent swing high and low
    fibonacci_data = calculate_fibonacci_levels(nearest_swing_high, nearest_swing_low, price)

    return {
        "support_resistance": {
            "prior_day_high": prior_day_high,
            "prior_day_low": prior_day_low,
            "premarket_high": premarket_high,
            "premarket_low": premarket_low,
            "nearest_recent_swing_high": nearest_swing_high,
            "nearest_recent_swing_low": nearest_swing_low,
            "nearest_resistance": nearest_resistance,
            "nearest_support": nearest_support,
            "distance_to_resistance_dollars": distance_to_resistance,
            "distance_to_resistance_pct": distance_to_resistance_pct,
            "distance_to_support_dollars": distance_to_support,
            "distance_to_support_pct": distance_to_support_pct,
            "closed_above_resistance": close_above_resistance,
            "closed_below_support": close_below_support,
            "breakout_volume_confirmed": breakout_confirmation,
            "breakdown_volume_confirmed": breakdown_confirmation,
            "psychological_levels": {
                "half_dollar_support": float(half_dollar_support),
                "half_dollar_resistance": float(half_dollar_resistance),
                "whole_dollar_support": float(whole_dollar_support),
                "whole_dollar_resistance": float(whole_dollar_resistance),
            },
        },
        "fibonacci_levels": fibonacci_data,
        "macd": {
            "bullish_crossover_last_3_candles": bullish_crossover,
            "bearish_crossover_last_3_candles": bearish_crossover,
            "current_macd": current_macd,
            "current_signal": current_signal,
            "current_histogram": current_hist,
            "histogram_direction": histogram_direction,
        },
    }


def market_regime(last, prev):
    """
    Determine market regime (BULLISH, BEARISH, NEUTRAL).
    
    Args:
        last: Current candle (Series with close, vwap, ema10, ema20, ema50)
        prev: Previous candle (Series with ema10)
        
    Returns:
        str: "BULLISH", "BEARISH", or "NEUTRAL"
    """
    regime_snapshot = classify_market_regime(last, prev)
    return regime_snapshot["market_regime"]


def classify_market_regime(last, prev):
    """
    Pure intraday market regime classification used by live and replay.

    Regime definitions:
    - BULLISH: close > vwap AND ema20 > ema50 AND ema50 rising vs prior candle
    - BEARISH: ema20 < ema50 AND ema50 falling vs prior candle, with close not materially above vwap
    - NEUTRAL: anything else

    Returns:
        Dict with market_regime and individual boolean condition flags.
    """
    close_price = float(last.close)
    vwap_price = float(last.vwap)
    price_above_vwap = bool(close_price > vwap_price)
    ema20_above_ema50 = bool(float(last.ema20) > float(last.ema50))
    ema50_rising = bool(float(last.ema50) > float(prev.ema50))
    price_above_vwap_pct = ((close_price - vwap_price) / vwap_price) if vwap_price else 0.0
    bearish_vwap_ok = close_price <= (vwap_price * (1.0 + REGIME_VWAP_TOLERANCE_PCT))

    bullish = price_above_vwap and ema20_above_ema50 and ema50_rising
    bearish = bearish_vwap_ok and (not ema20_above_ema50) and (not ema50_rising)

    if bullish:
        market_regime_value = "BULLISH"
    elif bearish:
        market_regime_value = "BEARISH"
    else:
        market_regime_value = "NEUTRAL"

    return {
        "market_regime": market_regime_value,
        "price_above_vwap": price_above_vwap,
        "price_above_vwap_pct": price_above_vwap_pct,
        "ema20_above_ema50": ema20_above_ema50,
        "ema50_rising": ema50_rising,
    }


def is_regime_aligned(direction, market_regime):
    """
    Return True when entry direction matches allowed market regime.

    CALL entries: BULLISH only
    PUT entries: BEARISH only
    """
    direction_upper = str(direction).upper()
    if direction_upper == "CALL":
        return market_regime == "BULLISH"
    if direction_upper == "PUT":
        return market_regime == "BEARISH"
    return False


def volume_momentum(df):
    """
    Analyze volume momentum.
    
    Args:
        df: DataFrame with volume column
        
    Returns:
        Dict with trend, volumes, ratio, and score adjustment
    """
    if len(df) < 12:
        return {
            "trend": "UNKNOWN",
            "current_volume": 0,
            "avg_volume": 0,
            "volume_ratio": 0,
            "score_adjustment": 0,
            "confidence": 0.0,
            "display_trend": "UNKNOWN",
        }

    vol = pd.to_numeric(df["volume"], errors="coerce").dropna()
    if len(vol) < 12:
        return {
            "trend": "UNKNOWN",
            "current_volume": 0,
            "avg_volume": 0,
            "volume_ratio": 0,
            "score_adjustment": 0,
            "confidence": 0.0,
            "display_trend": "UNKNOWN",
        }

    current_volume = float(vol.iloc[-1])
    short_avg = float(vol.iloc[-6:-1].mean())
    long_avg = float(vol.iloc[-21:-1].mean()) if len(vol) >= 21 else float(vol.iloc[:-1].mean())

    if short_avg <= 0 or long_avg <= 0:
        return {
            "trend": "UNKNOWN",
            "current_volume": current_volume,
            "avg_volume": short_avg,
            "volume_ratio": 0,
            "score_adjustment": 0,
            "confidence": 0.0,
            "display_trend": "UNKNOWN",
        }

    short_ratio = current_volume / short_avg
    long_ratio = current_volume / long_avg

    ema_fast_series = vol.ewm(span=3, adjust=False).mean()
    ema_slow_series = vol.ewm(span=10, adjust=False).mean()
    ema_fast = float(ema_fast_series.iloc[-1])
    ema_slow = float(ema_slow_series.iloc[-1]) if float(ema_slow_series.iloc[-1]) > 0 else 0.0
    ema_ratio = (ema_fast / ema_slow) if ema_slow > 0 else 1.0

    prior_baseline = float(vol.iloc[-8:-3].mean()) if len(vol) >= 8 else short_avg
    recent_baseline = float(vol.iloc[-3:].mean())
    momentum_ratio = (recent_baseline / prior_baseline) if prior_baseline > 0 else 1.0

    bull_votes = 0
    bull_votes += 1 if short_ratio >= 1.15 else 0
    bull_votes += 1 if long_ratio >= 1.05 else 0
    bull_votes += 1 if ema_ratio >= 1.03 else 0
    bull_votes += 1 if momentum_ratio >= 1.02 else 0

    bear_votes = 0
    bear_votes += 1 if short_ratio <= 0.90 else 0
    bear_votes += 1 if long_ratio <= 0.95 else 0
    bear_votes += 1 if ema_ratio <= 0.97 else 0
    bear_votes += 1 if momentum_ratio <= 0.98 else 0

    if bull_votes >= 3 and bull_votes > bear_votes:
        trend = "INCREASING"
        score_adjustment = 1
        confidence = (bull_votes / 4.0) * 100.0
    elif bear_votes >= 3 and bear_votes > bull_votes:
        trend = "DECREASING"
        score_adjustment = -1
        confidence = (bear_votes / 4.0) * 100.0
    else:
        trend = "NEUTRAL"
        score_adjustment = 0
        confidence = (max(bull_votes, bear_votes) / 4.0) * 100.0

    strength = "STRONG" if confidence >= 90 else ("MODERATE" if confidence >= 75 else "WEAK")
    display_trend = f"{trend} ({strength}, {confidence:.0f}%)"

    return {
        "trend": trend,
        "current_volume": current_volume,
        "avg_volume": short_avg,
        "volume_ratio": short_ratio,
        "volume_ratio_long": long_ratio,
        "ema_ratio": ema_ratio,
        "momentum_ratio": momentum_ratio,
        "score_adjustment": score_adjustment,
        "confidence": confidence,
        "display_trend": display_trend,
    }


def candle_quality(last):
    """
    Analyze candle structure and quality.
    
    Args:
        last: Current candle (Series with open, high, low, close)
        
    Returns:
        Dict with direction, body, range, body_pct, wicks
    """
    open_price = float(last.open)
    high = float(last.high)
    low = float(last.low)
    close = float(last.close)

    body = abs(close - open_price)
    candle_range = max(high - low, 0.01)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low

    if close > open_price:
        direction = "BULLISH"
    elif close < open_price:
        direction = "BEARISH"
    else:
        direction = "DOJI"

    body_pct = body / candle_range

    return {
        "direction": direction,
        "body": body,
        "range": candle_range,
        "body_pct": body_pct,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
    }


def momentum_freshness(df, direction="CALL", breakout_lookback=5):
    """Measure whether momentum is fresh (early) or exhausted (late).

    Returns a diagnostic dict with score, readable positives/penalties,
    breakout age, and EARLY/MID/LATE phase label.
    """
    if df is None or len(df) < 12:
        return {
            "score": 0,
            "positives": [],
            "penalties": [],
            "breakout_age_candles": None,
            "phase": "MID",
        }

    local = df.copy()
    for col in ["open", "high", "low", "close", "volume", "ema10", "ema20", "macd_hist"]:
        if col not in local.columns:
            return {
                "score": 0,
                "positives": [],
                "penalties": [f"missing_{col}"],
                "breakout_age_candles": None,
                "phase": "MID",
            }

    direction = str(direction or "CALL").upper()
    bullish = direction == "CALL"

    last = local.iloc[-1]
    prev = local.iloc[-2]

    score = 0
    positives = []
    penalties = []

    close_series = local["close"].astype(float)
    high_series = local["high"].astype(float)
    low_series = local["low"].astype(float)
    open_series = local["open"].astype(float)
    vol_series = local["volume"].astype(float)

    # 1) EMA10/EMA20 separation trend
    spread_now = float(last["ema10"] - last["ema20"])
    spread_prev = float(prev["ema10"] - prev["ema20"])
    if bullish:
        if spread_now > 0 and spread_now > spread_prev:
            score += 1
            positives.append("EMA10 separating farther above EMA20")
    else:
        if spread_now < 0 and spread_now < spread_prev:
            score += 1
            positives.append("EMA10 separating farther below EMA20")

    # 2) MACD histogram expansion
    hist_now = float(last["macd_hist"])
    hist_prev = float(prev["macd_hist"])
    if bullish:
        if hist_now > hist_prev:
            score += 1
            positives.append("MACD histogram expanding")
        else:
            score -= 1
            penalties.append("MACD histogram shrinking")
    else:
        if hist_now < hist_prev:
            score += 1
            positives.append("MACD histogram expanding bearish momentum")
        else:
            score -= 1
            penalties.append("MACD histogram shrinking bearish momentum")

    # 3) Breakout freshness and breakout age
    breakout_age = None
    if bullish:
        prior_extreme = high_series.shift(1).rolling(window=breakout_lookback, min_periods=3).max()
        breakout_flags = close_series > prior_extreme
    else:
        prior_extreme = low_series.shift(1).rolling(window=breakout_lookback, min_periods=3).min()
        breakout_flags = close_series < prior_extreme

    breakout_idx = [idx for idx, is_break in breakout_flags.fillna(False).items() if bool(is_break)]
    if breakout_idx:
        last_break_idx = breakout_idx[-1]
        breakout_age = int((len(local) - 1) - int(last_break_idx) + 1)
        if 1 <= breakout_age <= 3:
            score += 2
            positives.append(f"Entry within first {breakout_age} candle(s) after breakout")
        elif breakout_age >= 7:
            score -= 1
            penalties.append(f"Breakout is aging ({breakout_age} candles since break)")

    # 4) Volume participation
    avg_recent_vol = float(vol_series.iloc[-6:-1].mean()) if len(vol_series) >= 6 else float(vol_series.iloc[:-1].mean())
    current_vol = float(vol_series.iloc[-1])
    if avg_recent_vol > 0 and current_vol > avg_recent_vol:
        score += 1
        positives.append("Volume above recent average")

    # Penalty A: 5+ consecutive directional candles
    streak = 0
    for idx in range(len(local) - 1, -1, -1):
        o = float(open_series.iloc[idx])
        c = float(close_series.iloc[idx])
        if bullish and c > o:
            streak += 1
        elif (not bullish) and c < o:
            streak += 1
        else:
            break
    if streak >= 5:
        score -= 1
        penalties.append(f"{streak} consecutive {'bullish' if bullish else 'bearish'} candles before entry")

    # Penalty B: multiple upper/lower wick rejection near highs/lows
    wick_rejections = 0
    for idx in range(max(0, len(local) - 3), len(local)):
        o = float(open_series.iloc[idx])
        h = float(high_series.iloc[idx])
        l = float(low_series.iloc[idx])
        c = float(close_series.iloc[idx])
        rng = max(h - l, 1e-6)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        if bullish and (upper_wick / rng) >= 0.35:
            wick_rejections += 1
        if (not bullish) and (lower_wick / rng) >= 0.35:
            wick_rejections += 1
    if wick_rejections >= 2:
        score -= 1
        penalties.append("Multiple wick rejections near move extreme")

    # Penalty C: price stretched from EMA10
    ema10_now = float(last["ema10"])
    close_now = float(last["close"])
    if ema10_now > 0:
        stretch_pct = ((close_now - ema10_now) / ema10_now) * 100.0
        if bullish and stretch_pct > 0.35:
            score -= 1
            penalties.append("Price stretched too far above EMA10")
        if (not bullish) and stretch_pct < -0.35:
            score -= 1
            penalties.append("Price stretched too far below EMA10")

    # Penalty D: declining volume while price keeps trending same direction
    if len(local) >= 3:
        c1, c2, c3 = [float(x) for x in close_series.iloc[-3:].tolist()]
        v1, v2, v3 = [float(x) for x in vol_series.iloc[-3:].tolist()]
        if bullish and (c1 < c2 < c3) and (v1 > v2 > v3):
            score -= 1
            penalties.append("Declining volume during continued price rise")
        if (not bullish) and (c1 > c2 > c3) and (v1 > v2 > v3):
            score -= 1
            penalties.append("Declining volume during continued price decline")

    # Phase label
    phase = "MID"
    if breakout_age is not None:
        if breakout_age <= 3 and streak < 5 and score >= 1:
            phase = "EARLY"
        elif breakout_age >= 7 or streak >= 5:
            phase = "LATE"
    elif streak >= 5 or score <= -1:
        phase = "LATE"

    return {
        "score": int(score),
        "positives": positives,
        "penalties": penalties,
        "breakout_age_candles": breakout_age,
        "phase": phase,
    }


def score_call(last, prev):
    """
    Score a call (bullish) signal.
    
    Args:
        last: Current candle
        prev: Previous candle
        
    Returns:
        Tuple of (score: int, reasons: list of str)
    """
    score = 0
    reasons = []

    if last.close > last.vwap:
        score += 1
        reasons.append("price_above_vwap")
    if last.ema10 > last.ema20 > last.ema50:
        score += 2
        reasons.append("bull_ema_stack")
    if last.ema10 > prev.ema10:
        score += 1
        reasons.append("ema10_rising")
    if last.macd_hist > prev.macd_hist:
        score += 1
        reasons.append("macd_improving")
    if last.close > prev.high:
        score += 1
        reasons.append("breaks_prev_high")

    return score, reasons


def score_put(last, prev):
    """
    Score a put (bearish) signal.
    
    Args:
        last: Current candle
        prev: Previous candle
        
    Returns:
        Tuple of (score: int, reasons: list of str)
    """
    score = 0
    reasons = []

    if last.close < last.vwap:
        score += 1
        reasons.append("price_below_vwap")
    if last.ema10 < last.ema20 < last.ema50:
        score += 2
        reasons.append("bear_ema_stack")
    if last.ema10 < prev.ema10:
        score += 1
        reasons.append("ema10_falling")
    if last.macd_hist < prev.macd_hist:
        score += 1
        reasons.append("macd_weakening")
    if last.close < prev.low:
        score += 1
        reasons.append("breaks_prev_low")

    return score, reasons
