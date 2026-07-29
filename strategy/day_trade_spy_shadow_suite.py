"""Pure, research-only evaluators derived from the Day Trade SPY catalog.

The functions in this module do not import execution code, read configuration,
write files, or mutate trading state.  They only label facts already present
in completed candles, entry diagnostics, and an optional selected contract.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


MODEL_VERSION = "day-trade-spy-shadow-suite.v1"
EASTERN_TZ = ZoneInfo("America/New_York")
MINIMUM_STRUCTURAL_ROOM_PCT = 0.02
MAX_OPTION_SPREAD_PCT = 8.0
MAX_OPTION_ABSOLUTE_SPREAD = 0.05
MIN_OPTION_VOLUME = 400
MIN_OPTION_OPEN_INTEREST = 100


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = pd.Timestamp(value).to_pydatetime()
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(EASTERN_TZ)


def _frame(candles: pd.DataFrame | None) -> pd.DataFrame:
    if candles is None or candles.empty:
        return pd.DataFrame()
    frame = candles.copy()
    for field in ("open", "high", "low", "close", "volume", "ema10", "ema20", "vwap"):
        if field in frame:
            frame[field] = pd.to_numeric(frame[field], errors="coerce")
    return frame.dropna(subset=["open", "high", "low", "close"])


def _session_phase(candle_time: Any) -> str:
    captured = _timestamp(candle_time)
    if captured is None:
        return "UNAVAILABLE"
    minute = captured.hour * 60 + captured.minute
    if 570 <= minute < 630:
        return "OPENING"
    if 630 <= minute < 840:
        return "MIDDAY"
    if 840 <= minute < 945:
        return "LATE_SESSION"
    return "OUTSIDE_ENTRY_WINDOW"


def _accepted_break(frame: pd.DataFrame, direction: str) -> dict[str, Any]:
    if len(frame) < 7:
        return {
            "verdict": "UNAVAILABLE",
            "reason": "requires_seven_completed_candles",
            "inputs": {"completed_candles": len(frame)},
        }
    setup = frame.iloc[-7:-2]
    breakout = frame.iloc[-2]
    confirmation = frame.iloc[-1]
    trigger = float(setup["high"].max() if direction == "CALL" else setup["low"].min())
    breakout_close = float(breakout["close"])
    confirmation_close = float(confirmation["close"])
    broke = breakout_close > trigger if direction == "CALL" else breakout_close < trigger
    touched = (
        float(confirmation["low"]) <= trigger
        if direction == "CALL"
        else float(confirmation["high"]) >= trigger
    )
    held = confirmation_close >= trigger if direction == "CALL" else confirmation_close <= trigger
    followed_through = (
        confirmation_close >= breakout_close
        if direction == "CALL"
        else confirmation_close <= breakout_close
    )
    current_break = (
        confirmation_close > trigger
        if direction == "CALL"
        else confirmation_close < trigger
    )
    if broke and touched and held:
        verdict, reason = "ADMIT", "break_close_retest_hold_confirmed"
    elif broke:
        verdict, reason = "DELAY", "prior_break_not_yet_accepted"
    elif current_break:
        verdict, reason = "DELAY", "first_penetration_wait_for_retest"
    else:
        verdict, reason = "REJECT", "no_accepted_break"
    return {
        "verdict": verdict,
        "reason": reason,
        "inputs": {
            "trigger": round(trigger, 6),
            "breakout_close": breakout_close,
            "confirmation_close": confirmation_close,
            "break_close": broke,
            "retest_touched": touched,
            "retest_held": held,
            "followed_through": followed_through,
        },
    }


def _derived_structural_room(frame: pd.DataFrame, direction: str) -> dict[str, Any]:
    if len(frame) < 6:
        return {}
    close = float(frame.iloc[-1]["close"])
    prior = frame.iloc[-21:-1]
    if prior.empty or close <= 0:
        return {}
    if direction == "CALL":
        friction = float(prior["high"].max())
        dollars = max(0.0, friction - close)
        return {
            "nearest_resistance": friction,
            "distance_to_resistance_dollars": dollars,
            "distance_to_resistance_pct": dollars / close * 100.0,
        }
    friction = float(prior["low"].min())
    dollars = max(0.0, close - friction)
    return {
        "nearest_support": friction,
        "distance_to_support_dollars": dollars,
        "distance_to_support_pct": dollars / close * 100.0,
    }


def _structural_execution(
    frame: pd.DataFrame,
    direction: str,
    features: dict[str, Any],
    option: dict[str, Any],
) -> dict[str, Any]:
    structure = _object(features.get("support_resistance"))
    provenance = "captured_live"
    if not structure:
        structure = _derived_structural_room(frame, direction)
        provenance = "closed_candle_reconstruction" if structure else "UNAVAILABLE"
    room_key = "distance_to_resistance_pct" if direction == "CALL" else "distance_to_support_pct"
    room_pct = _number(structure.get(room_key))
    room_pass = room_pct is not None and room_pct >= MINIMUM_STRUCTURAL_ROOM_PCT

    symbol = str(option.get("symbol") or option.get("option_symbol") or "").strip()
    bid = _number(option.get("bid"))
    ask = _number(option.get("ask"))
    mark = _number(option.get("mark"))
    volume = _number(option.get("volume") if option.get("volume") is not None else option.get("totalVolume"))
    open_interest = _number(
        option.get("open_interest")
        if option.get("open_interest") is not None
        else option.get("openInterest")
    )
    quote_age_seconds = _number(option.get("quote_age_seconds"))
    spread = ask - bid if bid is not None and ask is not None and ask >= bid else None
    spread_pct = spread / mark * 100.0 if spread is not None and mark and mark > 0 else None
    quote_complete = bool(symbol and bid and ask and mark)
    liquid = (
        (volume is not None and volume >= MIN_OPTION_VOLUME)
        or (open_interest is not None and open_interest >= MIN_OPTION_OPEN_INTEREST)
    )
    execution_pass = bool(
        quote_complete
        and spread is not None
        and spread <= MAX_OPTION_ABSOLUTE_SPREAD
        and spread_pct is not None
        and spread_pct <= MAX_OPTION_SPREAD_PCT
        and liquid
    )
    if room_pct is None:
        verdict, reason = "UNAVAILABLE", "structural_room_unavailable"
    elif not room_pass:
        verdict, reason = "REJECT", "insufficient_structural_room"
    elif not quote_complete:
        verdict, reason = "UNAVAILABLE", "option_quote_unavailable"
    elif not execution_pass:
        verdict, reason = "REJECT", "option_not_executable"
    else:
        verdict, reason = "ADMIT", "structural_room_and_option_executable"
    return {
        "verdict": verdict,
        "reason": reason,
        "inputs": {
            "structural_room_pct": room_pct,
            "minimum_structural_room_pct": MINIMUM_STRUCTURAL_ROOM_PCT,
            "structural_room_pass": room_pass,
            "structure_provenance": provenance,
            "option_symbol": symbol or None,
            "bid": bid,
            "ask": ask,
            "mark": mark,
            "spread_dollars": round(spread, 6) if spread is not None else None,
            "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
            "volume": volume,
            "open_interest": open_interest,
            "expiration": option.get("expiration") or option.get("expirationDate"),
            "strike": _number(option.get("strike") or option.get("strikePrice")),
            "delta": _number(option.get("delta")),
            "implied_volatility": _number(
                option.get("volatility")
                if option.get("volatility") is not None
                else option.get("impliedVolatility")
            ),
            "quote_age_seconds": quote_age_seconds,
            "quote_source": option.get("quote_source"),
            "option_execution_pass": execution_pass,
        },
    }


def _opening_or_pullback(frame: pd.DataFrame, direction: str, candle_time: Any) -> dict[str, Any]:
    phase = _session_phase(candle_time)
    if len(frame) < 6:
        return {
            "verdict": "UNAVAILABLE",
            "reason": "requires_six_completed_candles",
            "inputs": {"session_phase": phase, "completed_candles": len(frame)},
        }
    recent = frame.iloc[-6:]
    last = recent.iloc[-1]
    candle_range = float(last["high"] - last["low"])
    close_location = (
        (float(last["close"]) - float(last["low"])) / candle_range
        if candle_range > 0
        else None
    )
    directional_close = (
        close_location is not None
        and (close_location >= 0.70 if direction == "CALL" else close_location <= 0.30)
    )
    ema10 = recent["ema10"] if "ema10" in recent else pd.Series(dtype=float)
    pullback_touched = False
    reclaimed = False
    if not ema10.empty and ema10.notna().all():
        prior = recent.iloc[-5:-1]
        prior_ema = ema10.iloc[-5:-1]
        if direction == "CALL":
            pullback_touched = bool((prior["low"].to_numpy() <= prior_ema.to_numpy()).any())
            reclaimed = float(last["close"]) > float(ema10.iloc[-1])
        else:
            pullback_touched = bool((prior["high"].to_numpy() >= prior_ema.to_numpy()).any())
            reclaimed = float(last["close"]) < float(ema10.iloc[-1])
    if phase == "OPENING":
        verdict = "ADMIT" if directional_close else "REJECT"
        reason = "opening_follow_through" if directional_close else "weak_opening_follow_through"
    elif phase in {"MIDDAY", "LATE_SESSION"}:
        verdict = "ADMIT" if pullback_touched and reclaimed and directional_close else "REJECT"
        reason = (
            "later_pullback_reclaim_confirmed"
            if verdict == "ADMIT"
            else "later_entry_without_qualified_pullback_reclaim"
        )
    else:
        verdict, reason = "UNAVAILABLE", "outside_entry_window"
    return {
        "verdict": verdict,
        "reason": reason,
        "inputs": {
            "session_phase": phase,
            "directional_close": directional_close,
            "close_location": round(close_location, 4) if close_location is not None else None,
            "pullback_touched_ema10": pullback_touched,
            "reclaimed_ema10": reclaimed,
        },
    }


def _congestion_reentry(
    frame: pd.DataFrame,
    direction: str,
    same_regime_attempt_count: int | None,
) -> dict[str, Any]:
    if len(frame) < 10:
        return {
            "verdict": "UNAVAILABLE",
            "reason": "requires_ten_completed_candles",
            "inputs": {"completed_candles": len(frame)},
        }
    recent = frame.iloc[-10:]
    ranges = (recent["high"] - recent["low"]).clip(lower=0)
    average_range = _number(ranges.mean())
    overlaps = 0
    for index in range(1, len(recent)):
        left, right = recent.iloc[index - 1], recent.iloc[index]
        if min(float(left["high"]), float(right["high"])) >= max(float(left["low"]), float(right["low"])):
            overlaps += 1
    overlap_ratio = overlaps / (len(recent) - 1)
    ema_compressed = None
    if average_range and average_range > 0 and {"ema10", "ema20"}.issubset(recent.columns):
        separation = abs(float(recent.iloc[-1]["ema10"]) - float(recent.iloc[-1]["ema20"]))
        ema_compressed = separation <= 0.25 * average_range
    vwap_crossings = None
    if "vwap" in recent and recent["vwap"].notna().all():
        signs = (recent["close"] - recent["vwap"]).apply(lambda value: 1 if value > 0 else -1 if value < 0 else 0)
        vwap_crossings = int(sum(signs.iloc[index] != signs.iloc[index - 1] for index in range(1, len(signs))))
    failed_closes = 0
    for index in range(1, len(recent)):
        prior, current = recent.iloc[index - 1], recent.iloc[index]
        if direction == "CALL" and float(current["high"]) > float(prior["high"]) and float(current["close"]) <= float(prior["high"]):
            failed_closes += 1
        if direction == "PUT" and float(current["low"]) < float(prior["low"]) and float(current["close"]) >= float(prior["low"]):
            failed_closes += 1
    congestion_flags = [
        overlap_ratio >= 0.70,
        ema_compressed is True,
        vwap_crossings is not None and vwap_crossings >= 3,
        failed_closes >= 2,
    ]
    congested = sum(congestion_flags) >= 2
    reentry_friction = same_regime_attempt_count is not None and same_regime_attempt_count >= 1
    verdict = "REJECT" if congested or reentry_friction else "ADMIT"
    reason = (
        "congestion_no_admission"
        if congested
        else "increased_reentry_friction"
        if reentry_friction
        else "no_congestion_or_reentry_veto"
    )
    return {
        "verdict": verdict,
        "reason": reason,
        "inputs": {
            "overlap_ratio": round(overlap_ratio, 4),
            "ema_compressed": ema_compressed,
            "vwap_crossings": vwap_crossings,
            "failed_closes": failed_closes,
            "congestion_flag_count": sum(congestion_flags),
            "same_regime_attempt_count": same_regime_attempt_count,
        },
    }


def _premise_reset(features: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    stop = _number(plan.get("stop") if plan.get("stop") is not None else plan.get("candidate_stop"))
    target = _number(plan.get("target") if plan.get("target") is not None else plan.get("candidate_target"))
    entry = _number(plan.get("entry") if plan.get("entry") is not None else plan.get("candidate_entry"))
    if stop is None:
        return {
            "verdict": "UNAVAILABLE",
            "reason": "original_invalidation_unavailable",
            "inputs": {"entry": entry, "original_stop": None, "original_target": target},
        }
    return {
        "verdict": "TRACK",
        "reason": "replay_original_stop_without_repair_or_carry",
        "inputs": {
            "entry": entry,
            "original_stop": stop,
            "original_target": target,
            "initial_quantity": _number(plan.get("quantity")),
            "repair_add_allowed": False,
            "target_to_carry_conversion_allowed": False,
            "end_of_session_exit_required": True,
            "captured_feature_stop": _number(features.get("original_stop")),
        },
    }


def evaluate_day_trade_spy_shadow_suite(
    candles: pd.DataFrame | None,
    direction: str,
    *,
    feature_payload: dict[str, Any] | str | None = None,
    option: dict[str, Any] | None = None,
    trade_plan: dict[str, Any] | None = None,
    same_regime_attempt_count: int | None = None,
    captured_at: datetime | None = None,
    provenance: str = "captured_live",
) -> dict[str, Any]:
    """Return an immutable five-test snapshot without affecting execution."""
    normalized_direction = str(direction or "").upper()
    frame = _frame(candles)
    features = _object(feature_payload)
    selected_option = _object(option)
    plan = _object(trade_plan)
    candle_time = frame.index[-1] if not frame.empty else captured_at
    captured = captured_at or datetime.now(EASTERN_TZ)
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=EASTERN_TZ)
    identity = {
        "model_version": MODEL_VERSION,
        "candle_time": str(candle_time),
        "direction": normalized_direction,
    }
    evaluation_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]
    valid_direction = normalized_direction in {"CALL", "PUT"}
    tests = (
        {
            "accepted_break": _accepted_break(frame, normalized_direction),
            "structural_room_execution": _structural_execution(
                frame, normalized_direction, features, selected_option
            ),
            "opening_vs_later_entry": _opening_or_pullback(
                frame, normalized_direction, candle_time
            ),
            "congestion_reentry": _congestion_reentry(
                frame, normalized_direction, same_regime_attempt_count
            ),
            "premise_reset_no_repair": _premise_reset(features, plan),
        }
        if valid_direction
        else {
            name: {"verdict": "UNAVAILABLE", "reason": "invalid_direction", "inputs": {}}
            for name in (
                "accepted_break",
                "structural_room_execution",
                "opening_vs_later_entry",
                "congestion_reentry",
                "premise_reset_no_repair",
            )
        }
    )
    return {
        "schema_version": MODEL_VERSION,
        "evaluation_id": evaluation_id,
        "captured_at": captured.astimezone(EASTERN_TZ).isoformat(),
        "candle_time": str(candle_time) if candle_time is not None else None,
        "direction": normalized_direction,
        "session_phase": _session_phase(candle_time),
        "provenance": provenance,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "tests": tests,
    }
