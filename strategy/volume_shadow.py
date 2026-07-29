"""Research-only volume telemetry and alternative checklist policies."""

from __future__ import annotations

import math
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


EASTERN_TZ = ZoneInfo("America/New_York")
MODEL_VERSION = "volume-shadow.v1"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _ratio(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None or baseline <= 0:
        return None
    return round(value / baseline, 4)


def _mean(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _policy_delta(
    ratio: float | None,
    *,
    direction_aligned: bool,
    quality_confirmed: bool = True,
) -> int:
    if not direction_aligned:
        return 0
    if ratio is not None and ratio >= 1.25 and quality_confirmed:
        return 1
    if ratio is not None and ratio <= 0.80:
        return -1
    return 0


def _session_context(candle_time: Any) -> tuple[int | None, str]:
    try:
        timestamp = pd.Timestamp(candle_time)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        timestamp = timestamp.tz_convert(EASTERN_TZ)
    except Exception:
        return None, "UNKNOWN"

    minute = (timestamp.hour * 60 + timestamp.minute) - (9 * 60 + 30)
    if minute < 0:
        return minute, "PREMARKET"
    if minute < 30:
        return minute, "OPENING_30"
    if minute < 120:
        return minute, "MORNING"
    if minute < 300:
        return minute, "MIDDAY"
    if minute < 390:
        return minute, "POWER_HOUR"
    return minute, "AFTER_HOURS"


def build_volume_shadow(
    candles,
    direction: str,
    *,
    observed_score: float | int | None = None,
    entry_threshold: float | int = 5,
) -> dict[str, Any]:
    """Describe volume and alternative score effects without changing live policy."""
    direction = str(direction or "").upper()
    unavailable = {
        "model_version": MODEL_VERSION,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "valid": False,
        "direction": direction,
        "reason": "insufficient_volume_history",
        "policies": {},
    }
    if candles is None or len(candles) < 6 or "volume" not in candles.columns:
        return unavailable

    local = candles.copy()
    volumes = pd.to_numeric(local["volume"], errors="coerce")
    current = _number(volumes.iloc[-1])
    prior = [_number(value) for value in volumes.iloc[:-1].tolist()]
    prior = [value for value in prior if value is not None and value >= 0]
    if current is None or len(prior) < 5:
        return unavailable

    prior_5 = prior[-5:]
    prior_20 = prior[-20:]
    average_5 = _mean(prior_5)
    average_20 = _mean(prior_20)
    median_20 = median(prior_20) if prior_20 else None
    ratio_5 = _ratio(current, average_5)
    ratio_20 = _ratio(current, average_20)
    ratio_median_20 = _ratio(current, median_20)

    standard_deviation_20 = None
    zscore_20 = None
    if len(prior_20) >= 2 and average_20 is not None:
        variance = sum((value - average_20) ** 2 for value in prior_20) / (len(prior_20) - 1)
        standard_deviation_20 = math.sqrt(variance)
        if standard_deviation_20 > 0:
            zscore_20 = round((current - average_20) / standard_deviation_20, 4)

    last = local.iloc[-1]
    open_price = _number(last.get("open"))
    high = _number(last.get("high"))
    low = _number(last.get("low"))
    close = _number(last.get("close"))
    candle_direction = (
        "CALL" if open_price is not None and close is not None and close > open_price
        else "PUT" if open_price is not None and close is not None and close < open_price
        else "NEUTRAL"
    )
    direction_aligned = candle_direction == direction
    candle_range = (
        max(high - low, 0.0)
        if high is not None and low is not None
        else 0.0
    )
    body_ratio = (
        abs(close - open_price) / candle_range
        if close is not None and open_price is not None and candle_range > 0
        else None
    )
    close_location = (
        (close - low) / candle_range
        if close is not None and low is not None and candle_range > 0
        else None
    )
    directional_close_confirmed = bool(
        direction_aligned
        and body_ratio is not None
        and body_ratio >= 0.50
        and close_location is not None
        and (
            (direction == "CALL" and close_location >= 0.70)
            or (direction == "PUT" and close_location <= 0.30)
        )
    )

    live_delta = _policy_delta(ratio_5, direction_aligned=direction_aligned)
    score = _number(observed_score)
    threshold = _number(entry_threshold) or 5.0
    score_without_live_volume = (
        round(score - live_delta, 4) if score is not None else None
    )

    policy_deltas = {
        "live_5bar": live_delta,
        "no_volume_adjustment": 0,
        "average_20bar": _policy_delta(
            ratio_20,
            direction_aligned=direction_aligned,
        ),
        "median_20bar": _policy_delta(
            ratio_median_20,
            direction_aligned=direction_aligned,
        ),
        "quality_confirmed_20bar": _policy_delta(
            ratio_20,
            direction_aligned=direction_aligned,
            quality_confirmed=directional_close_confirmed,
        ),
    }
    policies = {}
    for name, delta in policy_deltas.items():
        alternative_score = (
            round(score_without_live_volume + delta, 4)
            if score_without_live_volume is not None
            else None
        )
        policies[name] = {
            "score_delta": delta,
            "alternative_score": alternative_score,
            "would_pass_score_threshold": (
                alternative_score >= threshold
                if alternative_score is not None
                else None
            ),
        }

    minute_of_session, session_segment = _session_context(getattr(last, "name", None))
    return {
        "model_version": MODEL_VERSION,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "valid": True,
        "direction": direction,
        "current_volume": round(current, 4),
        "average_volume_5": round(average_5, 4) if average_5 is not None else None,
        "average_volume_20": round(average_20, 4) if average_20 is not None else None,
        "median_volume_20": round(median_20, 4) if median_20 is not None else None,
        "relative_volume_5": ratio_5,
        "relative_volume_20": ratio_20,
        "relative_volume_median_20": ratio_median_20,
        "volume_zscore_20": zscore_20,
        "volume_standard_deviation_20": (
            round(standard_deviation_20, 4)
            if standard_deviation_20 is not None
            else None
        ),
        "candle_direction": candle_direction,
        "direction_aligned_with_candle": direction_aligned,
        "candle_body_ratio": round(body_ratio, 4) if body_ratio is not None else None,
        "candle_close_location": (
            round(close_location, 4) if close_location is not None else None
        ),
        "directional_close_confirmed": directional_close_confirmed,
        "minute_of_session": minute_of_session,
        "session_segment": session_segment,
        "time_of_day_baseline_bucket": (
            int(minute_of_session // 15) * 15
            if minute_of_session is not None and 0 <= minute_of_session < 390
            else None
        ),
        "time_of_day_relative_volume": None,
        "time_of_day_baseline_sessions": 0,
        "observed_score": score,
        "score_without_live_volume": score_without_live_volume,
        "entry_threshold": threshold,
        "policies": policies,
        "policy_note": (
            "All alternatives are shadow-only. Time-of-day normalization is "
            "computed later from prior-session 15-minute buckets."
        ),
    }
