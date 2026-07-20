"""
Historical signal replay engine for backtesting.

Replays completed candles through the McLeod Alpha strategy,
generating buy/sell signal evaluations without executing trades.
"""

import pandas as pd
from datetime import datetime, date, time as dt_time
from zoneinfo import ZoneInfo
from pathlib import Path
import json

from backtesting.data_loader import classify_candle, TIMEZONE
from backtesting.replay_engine import ReplayEngine
from engine.brain import Brain
from strategy.signals import (
    add_indicators,
    build_feature_snapshot,
    classify_market_regime,
    momentum_freshness,
)


ENTRY_SCORE_THRESHOLD = 5
CONTINUATION_QUALITY_MIN_SCORE = 3.0
CONFIDENCE_MIN_SCORE = 2.5


def _safe_float(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _clamp01(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def trend_lifecycle_engine(df, direction="CALL", breakout_lookback=5):
    """Track trend lifecycle from last EMA10/EMA20 crossover."""
    direction = str(direction or "CALL").upper()
    bullish = direction == "CALL"

    empty = {
        "direction": direction,
        "trend_origin_index": 0,
        "trend_origin_price": 0.0,
        "trend_age_candles": 0,
        "trend_age_minutes": 0.0,
        "continuation_legs": 0,
        "structure_count": 0,
        "distance_from_origin_points": 0.0,
        "distance_from_origin_pct": 0.0,
        "trend_phase": "UNKNOWN",
        "trend_energy_score": 0.0,
    }

    if df is None or len(df) < 5:
        return empty

    required_cols = ["close", "high", "low", "ema10", "ema20"]
    if any(col not in df.columns for col in required_cols):
        return empty

    local = df.copy().reset_index(drop=True)
    close = local["close"].astype(float)
    high = local["high"].astype(float)
    low = local["low"].astype(float)
    ema10 = local["ema10"].astype(float)
    ema20 = local["ema20"].astype(float)

    if bullish:
        crossover_flags = (ema10 > ema20) & (ema10.shift(1) <= ema20.shift(1))
    else:
        crossover_flags = (ema10 < ema20) & (ema10.shift(1) >= ema20.shift(1))

    crossover_idx = [int(i) for i, flag in crossover_flags.fillna(False).items() if bool(flag)]
    trend_origin_idx = crossover_idx[-1] if crossover_idx else 0

    trend_age_candles = max((len(local) - 1) - trend_origin_idx, 0)

    trend_age_minutes = float(trend_age_candles)
    if "datetime" in local.columns:
        dt_series = pd.to_datetime(local["datetime"], utc=True, errors="coerce")
        if dt_series.notna().all():
            dt_origin = dt_series.iloc[trend_origin_idx]
            dt_last = dt_series.iloc[-1]
            trend_age_minutes = max((dt_last - dt_origin).total_seconds() / 60.0, 0.0)
    elif "timestamp" in local.columns:
        ts_series = pd.to_datetime(local["timestamp"], utc=True, errors="coerce")
        if ts_series.notna().all():
            ts_origin = ts_series.iloc[trend_origin_idx]
            ts_last = ts_series.iloc[-1]
            trend_age_minutes = max((ts_last - ts_origin).total_seconds() / 60.0, 0.0)

    if bullish:
        prior_extreme = high.shift(1).rolling(window=breakout_lookback, min_periods=3).max()
        breakout_flags = (close > prior_extreme).fillna(False)
    else:
        prior_extreme = low.shift(1).rolling(window=breakout_lookback, min_periods=3).min()
        breakout_flags = (close < prior_extreme).fillna(False)

    continuation_legs = 0
    in_leg = False
    for idx in range(trend_origin_idx, len(local)):
        is_break = bool(breakout_flags.iloc[idx])
        if is_break and not in_leg:
            continuation_legs += 1
            in_leg = True
        elif not is_break:
            in_leg = False

    structure_count = 0
    for idx in range(max(trend_origin_idx + 1, 1), len(local)):
        if bullish and _safe_float(high.iloc[idx]) > _safe_float(high.iloc[idx - 1]):
            structure_count += 1
        if (not bullish) and _safe_float(low.iloc[idx]) < _safe_float(low.iloc[idx - 1]):
            structure_count += 1

    origin_price = _safe_float(close.iloc[trend_origin_idx])
    last_price = _safe_float(close.iloc[-1])
    if bullish:
        distance_points = last_price - origin_price
    else:
        distance_points = origin_price - last_price
    distance_pct = (distance_points / origin_price) * 100.0 if abs(origin_price) > 1e-9 else 0.0

    if trend_age_minutes <= 45:
        trend_phase = "EARLY"
    elif trend_age_minutes <= 120:
        trend_phase = "MIDDLE"
    else:
        trend_phase = "LATE"

    age_factor = max(0.0, min(1.0, 1.0 - (trend_age_minutes / 240.0)))
    if continuation_legs <= 2:
        legs_factor = 1.0
    elif continuation_legs == 3:
        legs_factor = 0.5
    else:
        legs_factor = 0.0
    structure_factor = max(0.0, min(1.0, structure_count / 6.0))
    distance_factor = max(0.0, min(1.0, distance_pct / 0.8))
    trend_energy_score = round(5.0 * ((0.35 * age_factor) + (0.25 * legs_factor) + (0.20 * structure_factor) + (0.20 * distance_factor)), 2)

    return {
        "direction": direction,
        "trend_origin_index": int(trend_origin_idx),
        "trend_origin_price": round(origin_price, 4),
        "trend_age_candles": int(trend_age_candles),
        "trend_age_minutes": round(trend_age_minutes, 1),
        "continuation_legs": int(continuation_legs),
        "structure_count": int(structure_count),
        "distance_from_origin_points": round(distance_points, 4),
        "distance_from_origin_pct": round(distance_pct, 3),
        "trend_phase": trend_phase,
        "trend_energy_score": trend_energy_score,
    }


def trend_stage_engine(lifecycle):
    """Map trend lifecycle into Stage 1-5 maturity bucket."""
    age_m = _safe_float((lifecycle or {}).get("trend_age_minutes", 0.0))
    legs = int((lifecycle or {}).get("continuation_legs", 0) or 0)
    distance_pct = _safe_float((lifecycle or {}).get("distance_from_origin_pct", 0.0))
    energy = _safe_float((lifecycle or {}).get("trend_energy_score", 0.0))

    if age_m <= 20 and legs <= 1:
        stage, label = 1, "INITIATION"
    elif age_m <= 60 and legs <= 2:
        stage, label = 2, "EARLY_CONTINUATION"
    elif age_m <= 120 and legs <= 3:
        stage, label = 3, "ESTABLISHED"
    elif age_m <= 180 and legs <= 4:
        stage, label = 4, "MATURE"
    else:
        stage, label = 5, "LATE_EXHAUSTION"

    if energy <= 1.5 and stage < 5:
        stage += 1
    if distance_pct >= 1.2 and stage < 5:
        stage += 1

    return {"stage": int(min(stage, 5)), "label": label}


def momentum_acceleration_score(df, direction="CALL"):
    """Score 0-5 acceleration from existing momentum/price/volume behavior."""
    if df is None or len(df) < 5:
        return {"score": 0.0, "components": {}}

    direction = str(direction or "CALL").upper()
    bullish = direction == "CALL"
    local = df.copy().reset_index(drop=True)
    required_cols = ["close", "ema10", "ema20", "macd_hist", "volume"]
    if any(col not in local.columns for col in required_cols):
        return {"score": 0.0, "components": {"missing_columns": True}}

    close = local["close"].astype(float)
    ema10 = local["ema10"].astype(float)
    ema20 = local["ema20"].astype(float)
    macd_hist = local["macd_hist"].astype(float)
    vol = local["volume"].astype(float)

    h0 = _safe_float(macd_hist.iloc[-1])
    h1 = _safe_float(macd_hist.iloc[-2])
    h2 = _safe_float(macd_hist.iloc[-3])
    hist_velocity = h0 - h1
    hist_accel = (h0 - h1) - (h1 - h2)
    if bullish:
        hist_component = 1.0 if hist_velocity > 0 and hist_accel >= 0 else (0.5 if hist_velocity > 0 else 0.0)
    else:
        hist_component = 1.0 if hist_velocity < 0 and hist_accel <= 0 else (0.5 if hist_velocity < 0 else 0.0)

    spread_now = _safe_float(ema10.iloc[-1] - ema20.iloc[-1])
    spread_prev = _safe_float(ema10.iloc[-2] - ema20.iloc[-2])
    spread_delta = spread_now - spread_prev
    if bullish:
        spread_component = 1.0 if spread_delta > 0 and spread_now > 0 else 0.0
    else:
        spread_component = 1.0 if spread_delta < 0 and spread_now < 0 else 0.0

    c0 = _safe_float(close.iloc[-1])
    c1 = _safe_float(close.iloc[-2])
    c2 = _safe_float(close.iloc[-3])
    impulse = (c0 - c1) - (c1 - c2)
    if bullish:
        impulse_component = 1.0 if impulse > 0 else (0.5 if (c0 - c1) > 0 else 0.0)
    else:
        impulse_component = 1.0 if impulse < 0 else (0.5 if (c0 - c1) < 0 else 0.0)

    v0 = _safe_float(vol.iloc[-1])
    vref = _safe_float(vol.iloc[-6:-1].mean(), 0.0) if len(vol) >= 6 else _safe_float(vol.iloc[:-1].mean(), 0.0)
    vol_ratio = (v0 / vref) if vref > 0 else 0.0
    volume_component = 1.0 if vol_ratio >= 1.15 else (0.5 if vol_ratio >= 1.0 else 0.0)

    score = round(5.0 * ((hist_component + spread_component + impulse_component + volume_component) / 4.0), 2)
    return {
        "score": score,
        "components": {
            "macd_hist_acceleration": {"score": hist_component, "velocity": round(hist_velocity, 6), "acceleration": round(hist_accel, 6)},
            "ema_spread_acceleration": {"score": spread_component, "delta": round(spread_delta, 6)},
            "price_impulse": {"score": impulse_component, "acceleration": round(impulse, 6)},
            "volume_confirmation": {"score": volume_component, "ratio": round(vol_ratio, 3)},
        },
    }


def trend_efficiency_score(df, direction="CALL", lookback=10):
    """Score 0-5 for how cleanly price has trended over the last 8-10 candles."""
    if df is None or len(df) < 8:
        return {"score": 0.0, "components": {}}

    direction = str(direction or "CALL").upper()
    bullish = direction == "CALL"
    local = df.copy().reset_index(drop=True)
    required_cols = ["open", "high", "low", "close", "ema10", "ema20"]
    if any(col not in local.columns for col in required_cols):
        return {"score": 0.0, "components": {"missing_columns": True}}

    window = max(8, min(int(lookback), len(local)))
    tail = local.iloc[-window:].reset_index(drop=True)
    open_ = tail["open"].astype(float)
    high = tail["high"].astype(float)
    low = tail["low"].astype(float)
    close = tail["close"].astype(float)
    ema10 = tail["ema10"].astype(float)
    ema20 = tail["ema20"].astype(float)

    high_steps = 0
    low_steps = 0
    color_flips = 0
    ema_violations = 0
    opposing_body_hits = 0
    bodies = []
    opposing_wick_ratios = []
    spreads = []
    spread_expansions = 0
    signed_closes = []
    current_ema_streak = 0
    max_ema_streak = 0

    for idx in range(window):
        o = _safe_float(open_.iloc[idx])
        h = _safe_float(high.iloc[idx])
        l = _safe_float(low.iloc[idx])
        c = _safe_float(close.iloc[idx])
        e10 = _safe_float(ema10.iloc[idx])
        e20 = _safe_float(ema20.iloc[idx])
        candle_range = max(h - l, 1e-9)
        body = abs(c - o)
        bodies.append(body)

        if bullish:
            above_ema = c >= e10
            opposing_body = max(o - c, 0.0)
            opposing_wick = max(h - max(o, c), 0.0)
            signed_close = c
            spread = e10 - e20
        else:
            above_ema = c <= e10
            opposing_body = max(c - o, 0.0)
            opposing_wick = max(min(o, c) - l, 0.0)
            signed_close = -c
            spread = e20 - e10

        opposing_wick_ratios.append(opposing_wick / candle_range)
        signed_closes.append(signed_close)
        spreads.append(spread)

        if above_ema:
            current_ema_streak += 1
            max_ema_streak = max(max_ema_streak, current_ema_streak)
        else:
            ema_violations += 1
            current_ema_streak = 0

        if idx > 0:
            prev_h = _safe_float(high.iloc[idx - 1])
            prev_l = _safe_float(low.iloc[idx - 1])
            if bullish:
                if h >= prev_h:
                    high_steps += 1
                if l >= prev_l:
                    low_steps += 1
            else:
                if h <= prev_h:
                    high_steps += 1
                if l <= prev_l:
                    low_steps += 1

            prev_color = _safe_float(close.iloc[idx - 1]) >= _safe_float(open_.iloc[idx - 1])
            cur_color = c >= o
            if prev_color != cur_color:
                color_flips += 1

            if spread > 0 and spread > spreads[idx - 1]:
                spread_expansions += 1

        avg_body_so_far = max(sum(bodies) / len(bodies), 1e-9)
        if opposing_body > avg_body_so_far * 0.9:
            opposing_body_hits += 1

    transitions = max(window - 1, 1)
    structure_component = _clamp01(((high_steps / transitions) + (low_steps / transitions)) / 2.0)
    ema_streak_component = _clamp01(max_ema_streak / float(window))
    ema_hold_component = _clamp01((0.65 * ema_streak_component) + (0.35 * (1.0 - (ema_violations / float(window)))))
    spread_sign_component = _clamp01(sum(1 for s in spreads if s > 0) / float(window))
    spread_expand_component = _clamp01(spread_expansions / transitions)
    ema_separation_component = _clamp01((spread_sign_component + spread_expand_component) / 2.0)

    signed_start = signed_closes[0]
    signed_end = signed_closes[-1]
    net_progress = max(0.0, signed_end - signed_start)
    running_peak = signed_closes[0]
    max_drawback = 0.0
    for value in signed_closes[1:]:
        running_peak = max(running_peak, value)
        max_drawback = max(max_drawback, running_peak - value)
    avg_range = max(sum((_safe_float(high.iloc[i]) - _safe_float(low.iloc[i])) for i in range(window)) / float(window), 1e-9)
    drawback_scale = max(net_progress, avg_range * 1.5, 1e-9)
    pullback_component = _clamp01(1.0 - (max_drawback / drawback_scale))

    alternation_component = _clamp01(1.0 - (color_flips / transitions))
    opposing_body_component = _clamp01(1.0 - (opposing_body_hits / float(window)))
    half = max(1, window // 2)
    early_wicks = opposing_wick_ratios[:half]
    late_wicks = opposing_wick_ratios[-half:]
    early_wick_avg = sum(early_wicks) / len(early_wicks)
    late_wick_avg = sum(late_wicks) / len(late_wicks)
    wick_growth = late_wick_avg - early_wick_avg
    wick_component = _clamp01(1.0 - max(0.0, wick_growth) / 0.35)
    smoothness_component = _clamp01((alternation_component + opposing_body_component + wick_component) / 3.0)

    raw = (
        0.28 * structure_component
        + 0.24 * ema_hold_component
        + 0.18 * ema_separation_component
        + 0.18 * pullback_component
        + 0.12 * smoothness_component
    )
    score = round(5.0 * _clamp01(raw), 2)
    return {
        "score": score,
        "components": {
            "structure": round(structure_component, 3),
            "ema_hold": round(ema_hold_component, 3),
            "ema_separation": round(ema_separation_component, 3),
            "limited_pullback": round(pullback_component, 3),
            "smoothness": round(smoothness_component, 3),
            "color_alternation": round(alternation_component, 3),
            "opposing_body_control": round(opposing_body_component, 3),
            "wick_control": round(wick_component, 3),
            "ema_violations": int(ema_violations),
            "max_ema_streak": int(max_ema_streak),
            "max_drawback": round(max_drawback, 4),
            "net_progress": round(net_progress, 4),
        },
    }


def momentum_expansion_score_engine(df, direction="CALL", lookback=5):
    """Score 0-5 for whether momentum is expanding over the last 3-5 candles."""
    if df is None or len(df) < 5:
        return {"score": 0.0, "components": {}}

    direction = str(direction or "CALL").upper()
    bullish = direction == "CALL"
    local = df.copy().reset_index(drop=True)
    required_cols = ["open", "high", "low", "close", "ema10", "ema20", "macd_hist"]
    if any(col not in local.columns for col in required_cols):
        return {"score": 0.0, "components": {"missing_columns": True}}

    window = max(3, min(int(lookback), len(local)))
    tail = local.iloc[-window:].reset_index(drop=True)
    open_ = tail["open"].astype(float)
    high = tail["high"].astype(float)
    low = tail["low"].astype(float)
    close = tail["close"].astype(float)
    ema10 = tail["ema10"].astype(float)
    ema20 = tail["ema20"].astype(float)
    macd_hist = tail["macd_hist"].astype(float)

    signed_hist = [(_safe_float(v) if bullish else -_safe_float(v)) for v in macd_hist.tolist()]
    hist_increases = sum(1 for i in range(1, len(signed_hist)) if signed_hist[i] > signed_hist[i - 1])
    histogram_component = _clamp01(hist_increases / max(len(signed_hist) - 1, 1))

    spreads = []
    for i in range(window):
        spread = _safe_float(ema10.iloc[i] - ema20.iloc[i])
        spreads.append(spread if bullish else -spread)
    spread_increases = sum(1 for i in range(1, len(spreads)) if spreads[i] > spreads[i - 1] and spreads[i] > 0)
    ema_separation_component = _clamp01(spread_increases / max(len(spreads) - 1, 1))

    directional_moves = []
    bodies = []
    for i in range(window):
        bodies.append(abs(_safe_float(close.iloc[i]) - _safe_float(open_.iloc[i])))
        if i == 0:
            directional_moves.append(0.0)
        else:
            move = _safe_float(close.iloc[i]) - _safe_float(close.iloc[i - 1])
            directional_moves.append(move if bullish else -move)
    favorable_closes = sum(1 for move in directional_moves[1:] if move > 0)
    directional_close_component = _clamp01(favorable_closes / max(window - 1, 1))

    early_bodies = bodies[:-2] or bodies[:1]
    late_bodies = bodies[-2:]
    early_body_avg = sum(early_bodies) / max(len(early_bodies), 1)
    late_body_avg = sum(late_bodies) / max(len(late_bodies), 1)
    body_growth_ratio = ((late_body_avg - early_body_avg) / max(early_body_avg, 1e-9)) if early_body_avg > 0 else 0.0
    body_growth_component = _clamp01((body_growth_ratio + 0.10) / 0.50)

    overlap_ratios = []
    for i in range(1, window):
        prev_low = _safe_float(low.iloc[i - 1])
        prev_high = _safe_float(high.iloc[i - 1])
        cur_low = _safe_float(low.iloc[i])
        cur_high = _safe_float(high.iloc[i])
        overlap = max(0.0, min(prev_high, cur_high) - max(prev_low, cur_low))
        total_range = max(max(prev_high, cur_high) - min(prev_low, cur_low), 1e-9)
        overlap_ratios.append(overlap / total_range)
    avg_overlap = sum(overlap_ratios) / max(len(overlap_ratios), 1)
    overlap_component = _clamp01(1.0 - (avg_overlap / 0.75))

    raw = (
        0.24 * histogram_component
        + 0.22 * ema_separation_component
        + 0.20 * directional_close_component
        + 0.18 * body_growth_component
        + 0.16 * overlap_component
    )
    score = round(5.0 * _clamp01(raw), 2)
    return {
        "score": score,
        "components": {
            "expanding_histogram": round(histogram_component, 3),
            "ema_separation_expansion": round(ema_separation_component, 3),
            "directional_closes": round(directional_close_component, 3),
            "body_growth": round(body_growth_component, 3),
            "reduced_overlap": round(overlap_component, 3),
            "avg_overlap": round(avg_overlap, 3),
            "body_growth_ratio": round(body_growth_ratio, 3),
        },
    }


def confidence_score_engine(base_score, aligned, continuation_quality, momentum_acceleration, trend_efficiency, momentum_expansion, lifecycle, trend_stage):
    """Derive 0-5 confidence from interpreted existing signals."""
    base_norm = max(0.0, min(1.0, _safe_float(base_score) / max(1.0, float(ENTRY_SCORE_THRESHOLD))))
    cq_norm = max(0.0, min(1.0, _safe_float((continuation_quality or {}).get("score", 0.0)) / 5.0))
    ma_norm = max(0.0, min(1.0, _safe_float((momentum_acceleration or {}).get("score", 0.0)) / 5.0))
    tes_norm = max(0.0, min(1.0, _safe_float((trend_efficiency or {}).get("score", 0.0)) / 5.0))
    mes_norm = max(0.0, min(1.0, _safe_float((momentum_expansion or {}).get("score", 0.0)) / 5.0))
    energy_norm = max(0.0, min(1.0, _safe_float((lifecycle or {}).get("trend_energy_score", 0.0)) / 5.0))
    align_norm = 1.0 if aligned else 0.0

    stage_val = int((trend_stage or {}).get("stage", 5) or 5)
    if stage_val <= 2:
        stage_factor = 1.0
    elif stage_val == 3:
        stage_factor = 0.8
    elif stage_val == 4:
        stage_factor = 0.6
    else:
        stage_factor = 0.4

    raw = 0.20 * base_norm + 0.18 * cq_norm + 0.14 * ma_norm + 0.16 * tes_norm + 0.16 * mes_norm + 0.10 * energy_norm + 0.06 * align_norm
    score = round(5.0 * raw * stage_factor, 2)
    return {
        "score": score,
        "components": {
            "base_signal": round(base_norm * 5.0, 2),
            "continuation_quality": round(cq_norm * 5.0, 2),
            "momentum_acceleration": round(ma_norm * 5.0, 2),
            "trend_efficiency": round(tes_norm * 5.0, 2),
            "momentum_expansion": round(mes_norm * 5.0, 2),
            "trend_energy": round(energy_norm * 5.0, 2),
            "regime_alignment": round(align_norm * 5.0, 2),
            "stage_factor": stage_factor,
        },
    }


def continuation_quality_bullish(df, breakout_lookback=5):
    """Score bullish continuation setup quality on a normalized 0-5 scale."""
    if df is None or len(df) < 12:
        return {
            "score": 0.0,
            "min_required": CONTINUATION_QUALITY_MIN_SCORE,
            "passes": False,
            "trend_age_phase": "UNKNOWN",
            "completed_legs_since_crossover": 0,
            "trend_lifecycle": trend_lifecycle_engine(df, direction="CALL", breakout_lookback=breakout_lookback),
            "components": {
                "pullback_depth": {"score": 0.0, "depth_candles": 0},
                "macd_histogram_expansion": {"score": 0.0, "state": "UNKNOWN"},
                "trend_age": {"score": 0.0, "phase": "UNKNOWN", "age_candles": 0},
                "continuation_legs_since_crossover": {"score": 0.0, "legs": 0},
                "distance_from_ema10": {"score": 0.0, "distance_pct": 0.0},
                "breakout_volume_expansion": {"score": 0.0, "ratio": 0.0},
                "trend_lifecycle_energy": {"score": 0.0, "energy": 0.0},
                "trend_maturity_decay": {"score": 0.0, "decay": 0.0},
            },
        }

    required_cols = ["open", "high", "low", "close", "volume", "ema10", "ema20", "macd_hist"]
    if any(col not in df.columns for col in required_cols):
        return {
            "score": 0.0,
            "min_required": CONTINUATION_QUALITY_MIN_SCORE,
            "passes": False,
            "trend_age_phase": "UNKNOWN",
            "completed_legs_since_crossover": 0,
            "trend_lifecycle": trend_lifecycle_engine(df, direction="CALL", breakout_lookback=breakout_lookback),
            "components": {"missing_columns": {"score": 0.0}},
        }

    local = df.copy().reset_index(drop=True)
    close = local["close"].astype(float)
    high = local["high"].astype(float)
    volume = local["volume"].astype(float)
    ema10 = local["ema10"].astype(float)
    macd_hist = local["macd_hist"].astype(float)

    trend_lifecycle = trend_lifecycle_engine(local, direction="CALL", breakout_lookback=breakout_lookback)
    last_crossover = int(trend_lifecycle.get("trend_origin_index", 0))
    age_candles = int(trend_lifecycle.get("trend_age_candles", 0))
    age_minutes = _safe_float(trend_lifecycle.get("trend_age_minutes", float(age_candles)))

    prior_extreme = high.shift(1).rolling(window=breakout_lookback, min_periods=3).max()
    breakout_flags = (close > prior_extreme).fillna(False)

    leg_count = int(trend_lifecycle.get("continuation_legs", 0))

    breakout_idx = [int(i) for i, flag in breakout_flags.items() if bool(flag) and i >= last_crossover]
    last_breakout = breakout_idx[-1] if breakout_idx else (len(local) - 1)

    pullback_depth = 0
    i = max(last_breakout - 1, 0)
    while i > last_crossover:
        if _safe_float(close.iloc[i]) < _safe_float(close.iloc[i - 1]):
            pullback_depth += 1
            i -= 1
            continue
        break

    if 2 <= pullback_depth <= 5:
        pullback_score = 1.0
    elif pullback_depth in (1, 6):
        pullback_score = 0.5
    else:
        pullback_score = 0.0

    hist_delta = _safe_float(macd_hist.iloc[-1]) - _safe_float(macd_hist.iloc[-2])
    hist_tol = 1e-4
    if hist_delta > hist_tol:
        macd_state = "EXPANDING"
        macd_score = 1.0
    elif abs(hist_delta) <= hist_tol:
        macd_state = "FLAT"
        macd_score = 0.5
    else:
        macd_state = "SHRINKING"
        macd_score = 0.0

    if age_minutes <= 45:
        trend_phase = "EARLY"
        trend_age_score = 1.0
    elif age_minutes <= 120:
        trend_phase = "MIDDLE"
        trend_age_score = 0.5
    else:
        trend_phase = "LATE"
        trend_age_score = 0.0

    if leg_count <= 2:
        legs_score = 1.0
    elif leg_count == 3:
        legs_score = 0.5
    else:
        legs_score = 0.0

    lifecycle_energy = _safe_float(trend_lifecycle.get("trend_energy_score", 0.0))
    lifecycle_energy_score = max(0.0, min(1.0, lifecycle_energy / 5.0))

    ema10_now = _safe_float(ema10.iloc[-1], 1.0)
    close_now = _safe_float(close.iloc[-1], 0.0)
    distance_pct = ((close_now - ema10_now) / ema10_now) * 100.0 if abs(ema10_now) > 1e-9 else 0.0
    abs_distance = abs(distance_pct)
    if abs_distance <= 0.20:
        ema_reset_score = 1.0
    elif abs_distance <= 0.50:
        ema_reset_score = 0.5
    else:
        ema_reset_score = 0.0

    vol_ref_start = max(last_breakout - 5, 0)
    vol_ref_end = max(last_breakout, 1)
    ref_vol = volume.iloc[vol_ref_start:vol_ref_end]
    ref_avg = _safe_float(ref_vol.mean(), 0.0) if len(ref_vol) > 0 else 0.0
    breakout_vol = _safe_float(volume.iloc[last_breakout], 0.0)
    vol_ratio = (breakout_vol / ref_avg) if ref_avg > 0 else 0.0
    breakout_volume_score = 0.0
    if vol_ratio >= 1.20:
        breakout_volume_score = 1.0
    elif vol_ratio >= 1.00:
        breakout_volume_score = 0.5

    momentum_expansion = momentum_expansion_score_engine(local, direction="CALL")
    mes_norm = max(0.0, min(1.0, _safe_float((momentum_expansion or {}).get("score", 0.0)) / 5.0))

    component_scores = [
        pullback_score,
        macd_score,
        trend_age_score,
        legs_score,
        ema_reset_score,
        breakout_volume_score,
        lifecycle_energy_score,
    ]

    if age_minutes <= 45 and leg_count <= 2:
        maturity_decay = 0.0
    elif age_minutes <= 120 and leg_count <= 3:
        maturity_decay = 0.5
    else:
        maturity_decay = 1.0

    normalized_base = (((sum(component_scores) / len(component_scores)) * 0.82) + (mes_norm * 0.18)) * 5.0
    normalized_score = round(max(0.0, normalized_base - maturity_decay), 2)

    components = {
        "pullback_depth": {"score": pullback_score, "depth_candles": int(pullback_depth)},
        "macd_histogram_expansion": {
            "score": macd_score,
            "state": macd_state,
            "delta": round(hist_delta, 6),
        },
        "trend_age": {
            "score": trend_age_score,
            "phase": trend_phase,
            "age_candles": int(age_candles),
            "age_minutes": round(age_minutes, 1),
        },
        "continuation_legs_since_crossover": {"score": legs_score, "legs": int(leg_count)},
        "distance_from_ema10": {
            "score": ema_reset_score,
            "distance_pct": round(distance_pct, 3),
        },
        "breakout_volume_expansion": {
            "score": breakout_volume_score,
            "ratio": round(vol_ratio, 3),
            "breakout_candle_index": int(last_breakout),
        },
        "momentum_expansion": momentum_expansion,
        "trend_lifecycle_energy": {
            "score": lifecycle_energy_score,
            "energy": lifecycle_energy,
        },
        "trend_maturity_decay": {
            "score": 1.0 - min(maturity_decay / 1.0, 1.0),
            "decay": maturity_decay,
        },
    }

    return {
        "score": normalized_score,
        "min_required": CONTINUATION_QUALITY_MIN_SCORE,
        "passes": normalized_score >= CONTINUATION_QUALITY_MIN_SCORE,
        "trend_age_phase": trend_phase,
        "completed_legs_since_crossover": int(leg_count),
        "trend_lifecycle": trend_lifecycle,
        "components": components,
    }


def continuation_quality_score(df, direction="CALL", breakout_lookback=5):
    """Direction-aware continuation quality (0-5) using existing indicators only."""
    direction = str(direction or "CALL").upper()
    if direction == "CALL":
        result = continuation_quality_bullish(df, breakout_lookback=breakout_lookback)
        result["direction"] = "CALL"
        return result

    if df is None or len(df) == 0:
        result = continuation_quality_bullish(df, breakout_lookback=breakout_lookback)
        result["direction"] = "PUT"
        return result

    local = df.copy()
    for col in ["open", "close", "ema10", "ema20", "ema50", "vwap", "macd", "macd_signal", "macd_hist"]:
        if col in local.columns:
            local[col] = -pd.to_numeric(local[col], errors="coerce")
    if "high" in local.columns and "low" in local.columns:
        hi = -pd.to_numeric(local["low"], errors="coerce")
        lo = -pd.to_numeric(local["high"], errors="coerce")
        local["high"] = hi
        local["low"] = lo

    result = continuation_quality_bullish(local, breakout_lookback=breakout_lookback)
    result["trend_lifecycle"] = trend_lifecycle_engine(df, direction="PUT", breakout_lookback=breakout_lookback)
    result["direction"] = "PUT"
    return result


class SignalReplayEngine:
    """
    Replay historical candles and generate trading signal evaluations.
    
    Feeds candles through indicator calculation and scoring logic.
    Generates signal data for each candle during market hours.
    No trades are simulated.
    """
    
    MARKET_OPEN = dt_time(9, 30)
    MARKET_CLOSE_ENTRY = dt_time(15, 45)  # 3:45 PM - no new entries after this
    SIGNAL_CLOSE = dt_time(15, 44, 59)  # Cutoff for last signal evaluation
    
    def __init__(
        self,
        replay_engine: ReplayEngine,
        call_threshold: int = 5,
        put_threshold: int = 5,
    ):
        """
        Initialize signal replay engine.
        
        Args:
            replay_engine: ReplayEngine instance with historical candles
            call_threshold: Minimum call score to qualify for entry (default 5)
            put_threshold: Minimum put score to qualify for entry (default 5)
        """
        self.engine = replay_engine
        self.call_threshold = call_threshold
        self.put_threshold = put_threshold
        self.brain = Brain()
        self.candles_buffer = []
        self.signals = []
        
    def _is_eligible_for_signal(self, timestamp) -> bool:
        """Check if timestamp is eligible for signal generation."""
        time_et = timestamp.time()
        return self.MARKET_OPEN <= time_et <= self.SIGNAL_CLOSE
    
    def _classify_session(self, timestamp) -> str:
        """Classify candle as PREMARKET, REGULAR, or AFTER_HOURS."""
        return classify_candle(timestamp)
    
    def _process_indicators(self) -> pd.DataFrame:
        """Add indicators to candle buffer."""
        if len(self.candles_buffer) == 0:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.candles_buffer)
        df = add_indicators(df)
        return df
    
    def _generate_signals_for_step(self, step: int) -> dict:
        """
        Generate signal evaluation for current step.
        
        Args:
            step: Current replay step
            
        Returns:
            Dict with signal data or None if not eligible
        """
        if len(self.candles_buffer) < 2:
            return None
        
        # Get current and previous candles
        current_candle = self.candles_buffer[-1]
        
        # Check market hours eligibility
        if not self._is_eligible_for_signal(current_candle["timestamp"]):
            return None
        
        # Add indicators to full buffer
        df = self._process_indicators()
        if df.empty or len(df) < 2:
            return None
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        entry_decision = self.brain.evaluate_entry(last, prev, df)
        regime_snapshot = classify_market_regime(last, prev)
        regime = entry_decision["regime"]
        call_score = entry_decision["call_score"]
        put_score = entry_decision["put_score"]
        call_reasons = entry_decision["call_reasons"]
        put_reasons = entry_decision["put_reasons"]
        vol = entry_decision["volume"]
        call_momentum = momentum_freshness(df, direction="CALL")
        put_momentum = momentum_freshness(df, direction="PUT")
        
        # Build feature snapshot
        feature = build_feature_snapshot(df)

        call_aligned = entry_decision["direction"] == "CALL"
        put_aligned = entry_decision["direction"] == "PUT"
        call_lifecycle = trend_lifecycle_engine(df, direction="CALL")
        put_lifecycle = trend_lifecycle_engine(df, direction="PUT")
        call_stage = trend_stage_engine(call_lifecycle)
        put_stage = trend_stage_engine(put_lifecycle)
        call_continuation_quality = continuation_quality_score(df, direction="CALL")
        put_continuation_quality = continuation_quality_score(df, direction="PUT")
        call_momentum_acceleration = momentum_acceleration_score(df, direction="CALL")
        put_momentum_acceleration = momentum_acceleration_score(df, direction="PUT")
        call_trend_efficiency = trend_efficiency_score(df, direction="CALL")
        put_trend_efficiency = trend_efficiency_score(df, direction="PUT")
        call_momentum_expansion = momentum_expansion_score_engine(df, direction="CALL")
        put_momentum_expansion = momentum_expansion_score_engine(df, direction="PUT")
        call_confidence = confidence_score_engine(
            call_score,
            call_aligned,
            call_continuation_quality,
            call_momentum_acceleration,
            call_trend_efficiency,
            call_momentum_expansion,
            call_lifecycle,
            call_stage,
        )
        put_confidence = confidence_score_engine(
            put_score,
            put_aligned,
            put_continuation_quality,
            put_momentum_acceleration,
            put_trend_efficiency,
            put_momentum_expansion,
            put_lifecycle,
            put_stage,
        )

        # Brain owns live entry qualification. The replay-only fields below are
        # diagnostics and never alter that decision.
        call_qualified = entry_decision["direction"] == "CALL"
        put_qualified = entry_decision["direction"] == "PUT"
        protective_alarm_active = False
        
        return {
            "timestamp": current_candle["timestamp"],
            "close": float(current_candle["close"]),
            "market_regime": regime,
            "price_above_vwap": regime_snapshot["price_above_vwap"],
            "ema20_above_ema50": regime_snapshot["ema20_above_ema50"],
            "ema50_rising": regime_snapshot["ema50_rising"],
            "call_score": call_score,
            "put_score": put_score,
            "call_reasons": call_reasons,
            "put_reasons": put_reasons,
            "call_qualified": call_qualified,
            "put_qualified": put_qualified,
            "continuation_quality_call": call_continuation_quality,
            "continuation_quality_put": put_continuation_quality,
            "momentum_acceleration_call": call_momentum_acceleration,
            "momentum_acceleration_put": put_momentum_acceleration,
            "trend_efficiency_call": call_trend_efficiency,
            "trend_efficiency_put": put_trend_efficiency,
            "momentum_expansion_call": call_momentum_expansion,
            "momentum_expansion_put": put_momentum_expansion,
            "trend_stage_call": call_stage,
            "trend_stage_put": put_stage,
            "confidence_score_call": call_confidence,
            "confidence_score_put": put_confidence,
            "protective_stop_alarm_active": protective_alarm_active,
            "volume_trend": vol["trend"],
            "momentum_freshness_score_call": call_momentum.get("score", 0),
            "momentum_phase_call": call_momentum.get("phase", "MID"),
            "momentum_freshness_score_put": put_momentum.get("score", 0),
            "momentum_phase_put": put_momentum.get("phase", "MID"),
            "support_resistance": feature.get("support_resistance", {}),
            "macd_data": feature.get("macd", {}),
            "session": self._classify_session(current_candle["timestamp"]),
        }
    
    def replay(self) -> list:
        """
        Replay all candles and generate signals.
        
        Returns:
            List of signal dicts
        """
        self.signals = []
        step = 0
        
        while not self.engine.is_complete():
            # Get next candle
            candle, _ = self.engine.next_candle()
            
            # Add to buffer
            self.candles_buffer.append(candle)
            
            # Keep buffer limited (last 50 candles for indicator warmup)
            if len(self.candles_buffer) > 50:
                self.candles_buffer.pop(0)
            
            # Generate signal if eligible
            signal = self._generate_signals_for_step(step)
            if signal:
                signal["_step_idx"] = step  # Add absolute step index for trade simulator
                self.signals.append(signal)
            
            step += 1
        
        return self.signals
    
    def to_dataframe(self) -> pd.DataFrame:
        """
        Convert signals to DataFrame for analysis/export.
        
        Returns:
            DataFrame with signal data
        """
        if not self.signals:
            return pd.DataFrame()
        
        rows = []
        for signal in self.signals:
            rows.append({
                "timestamp": signal["timestamp"],
                "close": signal["close"],
                "market_regime": signal["market_regime"],
                "call_score": signal["call_score"],
                "put_score": signal["put_score"],
                "call_reasons": json.dumps(signal["call_reasons"]),
                "put_reasons": json.dumps(signal["put_reasons"]),
                "call_qualified": signal["call_qualified"],
                "put_qualified": signal["put_qualified"],
                "continuation_quality_call": signal.get("continuation_quality_call", {}).get("score"),
                "continuation_quality_put": signal.get("continuation_quality_put", {}).get("score"),
                "confidence_score_call": signal.get("confidence_score_call", {}).get("score"),
                "confidence_score_put": signal.get("confidence_score_put", {}).get("score"),
                "trend_stage_call": signal.get("trend_stage_call", {}).get("stage"),
                "trend_stage_put": signal.get("trend_stage_put", {}).get("stage"),
                "volume_trend": signal["volume_trend"],
                "momentum_freshness_score_call": signal.get("momentum_freshness_score_call"),
                "momentum_phase_call": signal.get("momentum_phase_call"),
                "momentum_freshness_score_put": signal.get("momentum_freshness_score_put"),
                "momentum_phase_put": signal.get("momentum_phase_put"),
                "session": signal["session"],
                "nearest_resistance": signal["support_resistance"].get("nearest_resistance"),
                "nearest_support": signal["support_resistance"].get("nearest_support"),
                "macd_current": signal["macd_data"].get("current_macd"),
                "macd_signal": signal["macd_data"].get("current_signal"),
                "macd_histogram": signal["macd_data"].get("current_histogram"),
                "histogram_direction": signal["macd_data"].get("histogram_direction"),
                "bullish_crossover": signal["macd_data"].get("bullish_crossover_last_3_candles"),
                "bearish_crossover": signal["macd_data"].get("bearish_crossover_last_3_candles"),
            })
        
        return pd.DataFrame(rows)
    
    def get_summary(self) -> dict:
        """
        Get summary statistics of signal replay.
        
        Returns:
            Dict with statistics
        """
        df_signals = pd.DataFrame(self.signals)
        
        if df_signals.empty:
            return {
                "total_candles_evaluated": 0,
                "regular_session_candles": 0,
                "call_qualified_signals": 0,
                "put_qualified_signals": 0,
                "by_score": {},
                "by_hour": {},
                "by_regime": {},
            }
        
        call_qualified = sum(1 for s in self.signals if s["call_qualified"])
        put_qualified = sum(1 for s in self.signals if s["put_qualified"])
        regular_session = sum(1 for s in self.signals if s["session"] == "REGULAR")
        
        # Group by score
        by_score = {}
        for signal in self.signals:
            call_score = signal["call_score"]
            put_score = signal["put_score"]
            for score in [call_score, put_score]:
                if score not in by_score:
                    by_score[score] = 0
                by_score[score] += 1
        
        # Group by hour
        by_hour = {}
        for signal in self.signals:
            hour = signal["timestamp"].hour
            if hour not in by_hour:
                by_hour[hour] = {"calls": 0, "puts": 0}
            if signal["call_qualified"]:
                by_hour[hour]["calls"] += 1
            if signal["put_qualified"]:
                by_hour[hour]["puts"] += 1
        
        # Group by regime
        by_regime = {}
        for signal in self.signals:
            regime = signal["market_regime"]
            if regime not in by_regime:
                by_regime[regime] = {"calls": 0, "puts": 0}
            if signal["call_qualified"]:
                by_regime[regime]["calls"] += 1
            if signal["put_qualified"]:
                by_regime[regime]["puts"] += 1
        
        return {
            "total_candles_evaluated": len(self.signals),
            "regular_session_candles": regular_session,
            "call_qualified_signals": call_qualified,
            "put_qualified_signals": put_qualified,
            "signals_by_score": by_score,
            "signals_by_hour": by_hour,
            "signals_by_regime": by_regime,
        }
