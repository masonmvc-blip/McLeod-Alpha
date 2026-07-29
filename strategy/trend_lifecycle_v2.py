"""Research-only trend lifecycle classification.

This module is deliberately isolated from live admission and trade management.
It produces deterministic shadow labels that can be joined to later outcomes.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


MODEL_VERSION = "trend_lifecycle_v2_shadow_1"
PHASES = (
    "UNKNOWN",
    "INITIATION",
    "EARLY_CONTINUATION",
    "ESTABLISHED",
    "MATURE",
    "LATE_EXHAUSTION",
)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if pd.notna(value) else default


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _empty(direction_hint: str | None, reason: str) -> dict[str, Any]:
    return {
        "model_version": MODEL_VERSION,
        "shadow_only": True,
        "valid": False,
        "reason": reason,
        "direction": "NEUTRAL",
        "direction_hint": direction_hint,
        "direction_hint_aligned": None,
        "direction_score": 0.0,
        "direction_confidence": 0.0,
        "trend_origin_index": None,
        "trend_origin_time": None,
        "trend_age_candles": 0,
        "active_leg": 0,
        "active_leg_origin_index": None,
        "active_leg_age_candles": 0,
        "confirmed_rebreaks": 0,
        "momentum_state": "NEUTRAL",
        "momentum_score": 0.0,
        "extension_atr": 0.0,
        "exhaustion_evidence": [],
        "exhaustion_evidence_count": 0,
        "phase": "UNKNOWN",
        "phase_number": 0,
        "phase_confidence": 0.0,
        "confirmation_candles": 2,
    }


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    true_range = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period, min_periods=min(5, period)).mean().bfill()


def _direction_evidence(frame: pd.DataFrame, atr: pd.Series) -> pd.Series:
    close = frame["close"].astype(float)
    ema10 = frame["ema10"].astype(float)
    ema20 = frame["ema20"].astype(float)
    scale = atr.replace(0, pd.NA).ffill().bfill().fillna(1.0)
    spread = ((ema10 - ema20) / scale).clip(-1.5, 1.5) / 1.5
    slope = ((ema10 - ema10.shift(3)) / (3.0 * scale)).clip(-1.0, 1.0)
    impulse = ((close - close.shift(3)) / (3.0 * scale)).clip(-1.0, 1.0)
    if "vwap" in frame.columns:
        vwap = frame["vwap"].astype(float)
        location = ((close - vwap) / scale).clip(-1.0, 1.0)
    else:
        location = pd.Series(0.0, index=frame.index)
    if "macd_hist" in frame.columns:
        hist = frame["macd_hist"].astype(float)
        hist_scale = hist.abs().rolling(20, min_periods=5).mean().replace(0, pd.NA)
        macd = (hist / hist_scale).clip(-1.0, 1.0).fillna(0.0)
    else:
        macd = pd.Series(0.0, index=frame.index)
    return (
        (0.35 * spread)
        + (0.20 * slope.fillna(0.0))
        + (0.20 * impulse.fillna(0.0))
        + (0.15 * location.fillna(0.0))
        + (0.10 * macd)
    ).clip(-1.0, 1.0)


def _confirmed_signs(evidence: pd.Series, threshold: float = 0.18) -> list[int]:
    raw = [1 if value >= threshold else -1 if value <= -threshold else 0 for value in evidence]
    confirmed: list[int] = []
    active = 0
    for idx, value in enumerate(raw):
        if idx and value and value == raw[idx - 1]:
            active = value
        elif value and value != active:
            # Hold the prior confirmed direction until the opposite direction
            # has persisted for two completed candles.
            pass
        confirmed.append(active)
    return confirmed


def _find_legs(
    frame: pd.DataFrame,
    *,
    origin: int,
    bullish: bool,
    atr: pd.Series,
) -> tuple[int, int, int]:
    """Count structural legs only after a confirmed pullback and rebreak."""
    high = frame["high"].astype(float).reset_index(drop=True)
    low = frame["low"].astype(float).reset_index(drop=True)
    close = frame["close"].astype(float).reset_index(drop=True)
    atr_values = atr.reset_index(drop=True)
    leg = 1
    leg_origin = origin
    extreme = high.iloc[origin] if bullish else low.iloc[origin]
    pullback_bars = 0
    pullback_extreme = low.iloc[origin] if bullish else high.iloc[origin]
    reference_extreme = extreme

    for idx in range(origin + 1, len(frame)):
        scale = max(_number(atr_values.iloc[idx], 0.0), 1e-9)
        if bullish:
            adverse = max(0.0, extreme - low.iloc[idx])
            if adverse >= 0.35 * scale:
                pullback_bars += 1
                pullback_extreme = min(pullback_extreme, low.iloc[idx])
            elif pullback_bars == 0:
                extreme = max(extreme, high.iloc[idx])
                reference_extreme = extreme
            if pullback_bars >= 2 and close.iloc[idx] > reference_extreme + 0.03 * scale:
                leg += 1
                leg_origin = idx
                extreme = high.iloc[idx]
                reference_extreme = extreme
                pullback_bars = 0
                pullback_extreme = low.iloc[idx]
        else:
            adverse = max(0.0, high.iloc[idx] - extreme)
            if adverse >= 0.35 * scale:
                pullback_bars += 1
                pullback_extreme = max(pullback_extreme, high.iloc[idx])
            elif pullback_bars == 0:
                extreme = min(extreme, low.iloc[idx])
                reference_extreme = extreme
            if pullback_bars >= 2 and close.iloc[idx] < reference_extreme - 0.03 * scale:
                leg += 1
                leg_origin = idx
                extreme = low.iloc[idx]
                reference_extreme = extreme
                pullback_bars = 0
                pullback_extreme = high.iloc[idx]

    return leg, leg_origin, max(0, leg - 1)


def classify_trend_lifecycle_v2(
    candles: pd.DataFrame,
    direction_hint: str | None = None,
) -> dict[str, Any]:
    """Classify direction, structural leg, momentum, and lifecycle phase.

    The output is research telemetry only. Two-candle confirmation and
    pullback/rebreak requirements provide hysteresis against one-bar flips.
    """
    hint = str(direction_hint or "").upper() or None
    if candles is None:
        return _empty(hint, "missing_frame")
    frame = candles.copy()
    if len(frame) < 8:
        return _empty(hint, "insufficient_candles")
    required = {"open", "high", "low", "close", "ema10", "ema20"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        return _empty(hint, f"missing_columns:{','.join(missing)}")
    frame = frame.reset_index().rename(columns={"index": "_time"})
    numeric = ["open", "high", "low", "close", "ema10", "ema20"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=numeric).reset_index(drop=True)
    if len(frame) < 8:
        return _empty(hint, "insufficient_valid_candles")

    atr = _atr(frame)
    evidence = _direction_evidence(frame, atr)
    confirmed = _confirmed_signs(evidence)
    sign = confirmed[-1]
    if sign == 0:
        return _empty(hint, "direction_not_confirmed")
    direction = "CALL" if sign > 0 else "PUT"
    bullish = sign > 0

    origin = len(frame) - 1
    while origin > 0 and confirmed[origin - 1] == sign:
        origin -= 1
    # A direction is not valid unless its two-candle confirmation exists.
    if origin < 1 or confirmed[origin] != sign:
        return _empty(hint, "trend_origin_not_confirmed")

    leg, leg_origin, rebreaks = _find_legs(frame, origin=origin, bullish=bullish, atr=atr)
    scale = max(_number(atr.iloc[-1], 0.0), 1e-9)
    close = frame["close"].astype(float)
    ema10 = frame["ema10"].astype(float)
    ema20 = frame["ema20"].astype(float)
    sign_float = float(sign)
    spread = sign_float * (ema10 - ema20)
    spread_change = (spread.iloc[-1] - spread.iloc[-4]) / (3.0 * scale)
    impulse_now = sign_float * (close.iloc[-1] - close.iloc[-4]) / (3.0 * scale)
    impulse_prior = sign_float * (close.iloc[-4] - close.iloc[-7]) / (3.0 * scale)
    impulse_change = impulse_now - impulse_prior
    if "macd_hist" in frame.columns:
        hist = frame["macd_hist"].astype(float) * sign_float
        hist_scale = max(_number(hist.abs().tail(20).mean(), 0.0), 1e-9)
        hist_change = (hist.iloc[-1] - hist.iloc[-3]) / hist_scale
    else:
        hist = pd.Series(0.0, index=frame.index)
        hist_change = 0.0
    momentum_score = _clip(
        (0.40 * _clip(spread_change))
        + (0.35 * _clip(impulse_change))
        + (0.25 * _clip(hist_change))
    )
    momentum_state = (
        "ACCELERATING" if momentum_score >= 0.18
        else "DECELERATING" if momentum_score <= -0.18
        else "STEADY"
    )

    extension_atr = sign_float * (close.iloc[-1] - ema10.iloc[-1]) / scale
    recent = frame.tail(3)
    evidence_flags: list[str] = []
    if momentum_state == "DECELERATING":
        evidence_flags.append("momentum_decelerating")
    if bullish:
        progress = recent["high"].astype(float).max() > frame["high"].astype(float).iloc[-6:-3].max()
        wick = (
            recent["high"].astype(float)
            - recent[["open", "close"]].astype(float).max(axis=1)
        ).iloc[-1]
    else:
        progress = recent["low"].astype(float).min() < frame["low"].astype(float).iloc[-6:-3].min()
        wick = (
            recent[["open", "close"]].astype(float).min(axis=1)
            - recent["low"].astype(float)
        ).iloc[-1]
    if not bool(progress):
        evidence_flags.append("failed_price_progress")
    body = abs(_number(frame["close"].iloc[-1]) - _number(frame["open"].iloc[-1]))
    if wick >= max(body * 1.25, scale * 0.30):
        evidence_flags.append("opposing_rejection_wick")
    if len(hist) >= 4 and hist.iloc[-1] < hist.iloc[-3]:
        evidence_flags.append("macd_fading")
    if extension_atr >= 1.25:
        evidence_flags.append("extended_from_ema10")

    exhaustion = (
        extension_atr >= 1.0
        and len(set(evidence_flags).intersection(
            {"momentum_decelerating", "failed_price_progress", "opposing_rejection_wick", "macd_fading"}
        )) >= 2
    )
    if exhaustion:
        phase = "LATE_EXHAUSTION"
    elif leg <= 1:
        phase = "INITIATION"
    elif leg == 2:
        phase = "EARLY_CONTINUATION"
    elif leg == 3:
        phase = "ESTABLISHED"
    else:
        phase = "MATURE"
    phase_number = PHASES.index(phase)

    direction_confidence = _clip(abs(_number(evidence.iloc[-1])), 0.0, 1.0)
    structure_confidence = min(1.0, 0.55 + (0.12 * rebreaks))
    phase_confidence = _clip(
        (0.55 * direction_confidence)
        + (0.30 * structure_confidence)
        + (0.15 if momentum_state != "NEUTRAL" else 0.0),
        0.0,
        1.0,
    )
    raw_time = frame["_time"].iloc[origin] if "_time" in frame.columns else None
    origin_time = None if raw_time is None or str(raw_time).isdigit() else str(raw_time)

    return {
        "model_version": MODEL_VERSION,
        "shadow_only": True,
        "valid": True,
        "reason": "classified",
        "direction": direction,
        "direction_hint": hint,
        "direction_hint_aligned": None if hint not in {"CALL", "PUT"} else hint == direction,
        "direction_score": round(_number(evidence.iloc[-1]), 4),
        "direction_confidence": round(direction_confidence, 4),
        "trend_origin_index": int(origin),
        "trend_origin_time": origin_time,
        "trend_age_candles": int((len(frame) - 1) - origin),
        "active_leg": int(leg),
        "active_leg_origin_index": int(leg_origin),
        "active_leg_age_candles": int((len(frame) - 1) - leg_origin),
        "confirmed_rebreaks": int(rebreaks),
        "momentum_state": momentum_state,
        "momentum_score": round(momentum_score, 4),
        "extension_atr": round(extension_atr, 4),
        "exhaustion_evidence": sorted(set(evidence_flags)),
        "exhaustion_evidence_count": len(set(evidence_flags)),
        "phase": phase,
        "phase_number": int(phase_number),
        "phase_confidence": round(phase_confidence, 4),
        "confirmation_candles": 2,
    }
