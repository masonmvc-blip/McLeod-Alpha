"""Pre-entry, shadow-only intraday market-state classification."""

from __future__ import annotations

from typing import Any


FRESH_TREND = "FRESH_TREND"
HEALTHY_CONTINUATION = "HEALTHY_CONTINUATION"
MATURE_TREND = "MATURE_TREND"
EXHAUSTION = "EXHAUSTION"
CHOP = "CHOP"


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def classify_market_state(frame) -> dict[str, Any]:
    """Classify the completed-candle frame without using future information."""
    if frame is None or len(frame) < 21:
        return {
            "state": CHOP,
            "trend_direction": "NEUTRAL",
            "reasons": ["insufficient_completed_candles"],
            "metrics": {"candle_count": 0 if frame is None else len(frame)},
        }

    recent = frame.iloc[-21:].copy()
    last = recent.iloc[-1]
    prior = recent.iloc[-2]
    close = recent["close"].astype(float)
    high = recent["high"].astype(float)
    low = recent["low"].astype(float)
    ranges = (high - low).clip(lower=0.0)
    average_range = max(float(ranges.iloc[:-1].mean()), 1e-9)
    net_move = float(close.iloc[-1] - close.iloc[-11])
    path_move = max(float(close.diff().abs().iloc[-10:].sum()), 1e-9)
    efficiency = abs(net_move) / path_move

    ema10 = _number(last.get("ema10"))
    ema20 = _number(last.get("ema20"))
    ema50 = _number(last.get("ema50"))
    ema10_slope = ema10 - _number(recent.iloc[-4].get("ema10"))
    ema20_slope = ema20 - _number(recent.iloc[-4].get("ema20"))
    separation = abs(ema10 - ema20) / average_range
    vwap_distance = (_number(last.get("close")) - _number(last.get("vwap"))) / average_range

    hist = recent["macd_hist"].astype(float) if "macd_hist" in recent else close * 0.0
    hist_slope = float(hist.iloc[-1] - hist.iloc[-4])
    histogram_expanding = abs(float(hist.iloc[-1])) > abs(float(hist.iloc[-4]))
    volume = recent["volume"].astype(float)
    volume_ratio = _number(last.get("volume")) / max(float(volume.iloc[:-1].mean()), 1e-9)

    bullish = ema10 > ema20 > ema50 and ema10_slope > 0 and ema20_slope >= 0 and vwap_distance > 0
    bearish = ema10 < ema20 < ema50 and ema10_slope < 0 and ema20_slope <= 0 and vwap_distance < 0
    trend_direction = "BULLISH" if bullish else "BEARISH" if bearish else "NEUTRAL"
    current_range_ratio = float(ranges.iloc[-1]) / average_range
    compressed = separation < 0.35 and current_range_ratio < 0.75
    aligned = bullish or bearish
    extension = abs(_number(last.get("close")) - ema10) / average_range
    momentum_fading = (bullish and hist_slope < 0) or (bearish and hist_slope > 0)
    opposite_close = (bullish and _number(last.get("close")) < _number(prior.get("close"))) or (
        bearish and _number(last.get("close")) > _number(prior.get("close"))
    )

    metrics = {
        "candle_count": len(frame),
        "directional_efficiency_10": round(efficiency, 4),
        "ema10_ema20_separation_in_avg_range": round(separation, 4),
        "ema10_slope_3": round(ema10_slope, 6),
        "ema20_slope_3": round(ema20_slope, 6),
        "vwap_distance_in_avg_range": round(vwap_distance, 4),
        "macd_histogram_slope_3": round(hist_slope, 6),
        "macd_histogram_expanding": histogram_expanding,
        "relative_volume_20": round(volume_ratio, 4),
        "extension_from_ema10_in_avg_range": round(extension, 4),
    }

    if not aligned and (compressed or efficiency < 0.35):
        return {"state": CHOP, "trend_direction": trend_direction, "reasons": ["ema_not_aligned", "low_directional_efficiency"], "metrics": metrics}
    if aligned and extension >= 1.5 and momentum_fading and (volume_ratio < 1.0 or opposite_close):
        return {"state": EXHAUSTION, "trend_direction": trend_direction, "reasons": ["extended_from_ema10", "momentum_fading", "participation_or_price_fading"], "metrics": metrics}
    if aligned and efficiency >= 0.60 and separation >= 0.50 and histogram_expanding and volume_ratio >= 1.0:
        return {"state": FRESH_TREND, "trend_direction": trend_direction, "reasons": ["aligned_expanding_emas", "high_directional_efficiency", "momentum_and_volume_expanding"], "metrics": metrics}
    if aligned and efficiency >= 0.45 and separation >= 0.35:
        return {"state": HEALTHY_CONTINUATION, "trend_direction": trend_direction, "reasons": ["aligned_ema_structure", "persistent_directional_move"], "metrics": metrics}
    return {"state": MATURE_TREND, "trend_direction": trend_direction, "reasons": ["trend_present_without_fresh_expansion"], "metrics": metrics}