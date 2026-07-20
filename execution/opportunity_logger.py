import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")
OPPORTUNITY_LOG_DIR = Path("data/reports/opportunity_logs")

_NEGATIVE_REASON_KEYS = {
    "volume_weakening_bullish_move",
    "volume_weakening_bearish_move",
}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_candle_time_to_et_iso(candle_time: Any) -> str:
    if isinstance(candle_time, datetime):
        if candle_time.tzinfo is None:
            candle_time = candle_time.replace(tzinfo=ZoneInfo("UTC"))
        return candle_time.astimezone(EASTERN_TZ).isoformat()

    text = _safe_str(candle_time)
    if not text:
        return datetime.now(EASTERN_TZ).isoformat()

    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(EASTERN_TZ).isoformat()


def _extract_positives_and_penalties(reasons: List[str]) -> tuple[List[str], List[str]]:
    positives: List[str] = []
    penalties: List[str] = []
    for reason in reasons:
        text = _safe_str(reason)
        if not text:
            continue
        if text in _NEGATIVE_REASON_KEYS:
            penalties.append(text)
        else:
            positives.append(text)
    return positives, penalties


def _extract_snapshot_metric(feature_payload: Dict[str, Any], direction: str, base_key: str) -> Any:
    direct = feature_payload.get(base_key)
    if direct is not None:
        return direct

    suffix = "call" if direction == "CALL" else "put"
    key = f"{base_key}_{suffix}"
    if key in feature_payload:
        return feature_payload.get(key)

    obj = feature_payload.get(key)
    if isinstance(obj, dict):
        return obj.get("score")

    return None


def _ema_metrics(df, last, bars: int = 3) -> Dict[str, Any]:
    ema10 = _safe_float(getattr(last, "ema10", None))
    ema20 = _safe_float(getattr(last, "ema20", None))

    ema10_slope = None
    ema20_slope = None
    if len(df) > bars:
        ref = df.iloc[-(bars + 1)]
        ref_ema10 = _safe_float(getattr(ref, "ema10", None))
        ref_ema20 = _safe_float(getattr(ref, "ema20", None))
        if ema10 is not None and ref_ema10 is not None:
            ema10_slope = ema10 - ref_ema10
        if ema20 is not None and ref_ema20 is not None:
            ema20_slope = ema20 - ref_ema20

    separation = None
    if ema10 is not None and ema20 is not None:
        separation = ema10 - ema20

    return {
        "ema10_slope_3": ema10_slope,
        "ema20_slope_3": ema20_slope,
        "ema10_ema20_separation": separation,
    }


def _macd_metrics(df, last, bars: int = 3) -> Dict[str, Any]:
    hist = _safe_float(getattr(last, "macd_hist", None))
    slope = None
    if len(df) > bars:
        ref = df.iloc[-(bars + 1)]
        ref_hist = _safe_float(getattr(ref, "macd_hist", None))
        if hist is not None and ref_hist is not None:
            slope = hist - ref_hist
    return {
        "macd_histogram_value": hist,
        "macd_histogram_slope_3": slope,
    }


def _candle_structure(last, prev, df) -> Dict[str, Any]:
    last_high = _safe_float(getattr(last, "high", None))
    last_low = _safe_float(getattr(last, "low", None))
    prev_high = _safe_float(getattr(prev, "high", None))
    prev_low = _safe_float(getattr(prev, "low", None))

    current_range = None
    if last_high is not None and last_low is not None:
        current_range = max(last_high - last_low, 0.0)

    avg_range = None
    if len(df) >= 6:
        recent = df.iloc[-6:-1]
        ranges = []
        for _, row in recent.iterrows():
            r_high = _safe_float(getattr(row, "high", None))
            r_low = _safe_float(getattr(row, "low", None))
            if r_high is not None and r_low is not None:
                ranges.append(max(r_high - r_low, 0.0))
        if ranges:
            avg_range = sum(ranges) / len(ranges)

    compression_status = "UNKNOWN"
    if current_range is not None and avg_range is not None and avg_range > 0:
        compression_status = "COMPRESSED" if current_range <= (0.6 * avg_range) else "EXPANDED"

    overlap_status = "UNKNOWN"
    if last_high is not None and last_low is not None and prev_high is not None and prev_low is not None:
        overlap_top = min(last_high, prev_high)
        overlap_bottom = max(last_low, prev_low)
        overlap_status = "OVERLAP" if overlap_top >= overlap_bottom else "NO_OVERLAP"

    broke_recent_high = None
    broke_recent_low = None
    close = _safe_float(getattr(last, "close", None))
    if close is not None and prev_high is not None:
        broke_recent_high = close > prev_high
    if close is not None and prev_low is not None:
        broke_recent_low = close < prev_low

    return {
        "candle_compression_status": compression_status,
        "candle_overlap_status": overlap_status,
        "recent_high_break": broke_recent_high,
        "recent_low_break": broke_recent_low,
    }


def _candle_research_metrics(last, prev, df) -> Dict[str, Any]:
    open_price = _safe_float(getattr(last, "open", None))
    high = _safe_float(getattr(last, "high", None))
    low = _safe_float(getattr(last, "low", None))
    close = _safe_float(getattr(last, "close", None))
    volume = _safe_float(getattr(last, "volume", None))

    candle_range = max((high or 0.0) - (low or 0.0), 0.0)
    body = abs((close or 0.0) - (open_price or 0.0))
    body_pct = round(body / candle_range, 4) if candle_range > 0 else None
    close_location_value = round((((close or 0.0) - (low or 0.0)) / candle_range) * 2.0 - 1.0, 4) if candle_range > 0 else None
    upper_wick_pct = round((max((high or 0.0) - max(open_price or 0.0, close or 0.0), 0.0) / candle_range), 4) if candle_range > 0 else None
    lower_wick_pct = round((max(min(open_price or 0.0, close or 0.0) - (low or 0.0), 0.0) / candle_range), 4) if candle_range > 0 else None

    recent = df.iloc[-21:-1] if len(df) >= 21 else df.iloc[:-1]
    recent_ranges = []
    recent_volumes = []
    for _, row in recent.iterrows():
        row_high = _safe_float(getattr(row, "high", None))
        row_low = _safe_float(getattr(row, "low", None))
        row_volume = _safe_float(getattr(row, "volume", None))
        if row_high is not None and row_low is not None:
            recent_ranges.append(max(row_high - row_low, 0.0))
        if row_volume is not None and row_volume > 0:
            recent_volumes.append(row_volume)
    average_range = sum(recent_ranges) / len(recent_ranges) if recent_ranges else None
    average_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else None

    prior_high = _safe_float(getattr(prev, "high", None))
    prior_low = _safe_float(getattr(prev, "low", None))
    structure = "MIXED"
    if high is not None and low is not None and prior_high is not None and prior_low is not None:
        if high > prior_high and low > prior_low:
            structure = "HIGHER_HIGH_HIGHER_LOW"
        elif high < prior_high and low < prior_low:
            structure = "LOWER_HIGH_LOWER_LOW"

    session_rows = []
    candle_time = getattr(last, "name", None)
    candle_date = getattr(candle_time, "date", lambda: None)()
    for index, row in df.iterrows():
        index_date = getattr(index, "date", lambda: None)()
        if candle_date is not None and index_date != candle_date:
            continue
        row_high = _safe_float(getattr(row, "high", None))
        row_low = _safe_float(getattr(row, "low", None))
        row_close = _safe_float(getattr(row, "close", None))
        row_volume = _safe_float(getattr(row, "volume", None))
        if None not in (row_high, row_low, row_close, row_volume) and row_volume > 0:
            session_rows.append((index, (row_high + row_low + row_close) / 3.0, row_volume, row_high, row_low))

    vwap = None
    vwap_slope_3 = None
    opening_range_high = None
    opening_range_low = None
    if session_rows:
        cumulative_volume = sum(row[2] for row in session_rows)
        vwap = sum(row[1] * row[2] for row in session_rows) / cumulative_volume if cumulative_volume else None
        if len(session_rows) >= 4:
            prior_rows = session_rows[:-3]
            prior_volume = sum(row[2] for row in prior_rows)
            if prior_volume:
                vwap_slope_3 = vwap - (sum(row[1] * row[2] for row in prior_rows) / prior_volume)
        opening_rows = []
        for index, _, _, row_high, row_low in session_rows:
            hour = getattr(index, "hour", None)
            minute = getattr(index, "minute", None)
            if hour == 9 and minute is not None and 30 <= minute < 60:
                opening_rows.append((row_high, row_low))
        if opening_rows:
            opening_range_high = max(row[0] for row in opening_rows)
            opening_range_low = min(row[1] for row in opening_rows)

    return {
        "candle_body_pct_of_range": body_pct,
        "candle_close_location_value": close_location_value,
        "candle_upper_wick_pct": upper_wick_pct,
        "candle_lower_wick_pct": lower_wick_pct,
        "candle_range": round(candle_range, 6),
        "candle_range_vs_20bar_avg": round(candle_range / average_range, 4) if average_range and average_range > 0 else None,
        "candle_relative_volume_20": round(volume / average_volume, 4) if volume is not None and average_volume and average_volume > 0 else None,
        "candle_structure": structure,
        "session_vwap": round(vwap, 6) if vwap is not None else None,
        "price_distance_from_session_vwap": round((close or 0.0) - vwap, 6) if close is not None and vwap is not None else None,
        "session_vwap_slope_3": round(vwap_slope_3, 6) if vwap_slope_3 is not None else None,
        "opening_range_high": opening_range_high,
        "opening_range_low": opening_range_low,
        "opening_range_state": "ABOVE" if opening_range_high is not None and close is not None and close > opening_range_high else "BELOW" if opening_range_low is not None and close is not None and close < opening_range_low else "INSIDE" if opening_range_high is not None else "UNAVAILABLE",
        "bullish_breakout_failure": bool(high is not None and prior_high is not None and close is not None and high > prior_high and close <= prior_high),
        "bearish_breakout_failure": bool(low is not None and prior_low is not None and close is not None and low < prior_low and close >= prior_low),
        "distance_to_recent_high_in_avg_range": round(((max([_safe_float(getattr(row, "high", None)) or 0.0 for _, row in recent.iterrows()]) - (close or 0.0)) / average_range), 4) if len(recent) and average_range and average_range > 0 and close is not None else None,
        "distance_to_recent_low_in_avg_range": round((((close or 0.0) - min([_safe_float(getattr(row, "low", None)) or 0.0 for _, row in recent.iterrows()])) / average_range), 4) if len(recent) and average_range and average_range > 0 and close is not None else None,
    }


def _direction_rejection_reason(
    direction: str,
    entered: bool,
    allow_entry: bool,
    in_position: bool,
    in_market_hours: bool,
    regime: str,
    score: int,
    entry_threshold: int,
) -> str | None:
    if entered:
        return None
    if not allow_entry:
        return "Startup stale candle guard"
    if in_position:
        return "Already in trade"
    if not in_market_hours:
        return "Market closed"

    if direction == "CALL":
        if regime != "BULL_TREND":
            return f"Regime mismatch ({regime})"
        if score < entry_threshold:
            return f"CALL score below threshold by {entry_threshold - score}"
        return "Not entered"

    if regime != "BEAR_TREND":
        return f"Regime mismatch ({regime})"
    if score < entry_threshold:
        return f"PUT score below threshold by {entry_threshold - score}"
    return "Not entered"


def _build_threshold_distance_payload(
    direction: str,
    score: int,
    entry_threshold: int,
    stage: Any,
    cq: Any,
    mas: Any,
    tes: Any,
    mes: Any,
    confidence: Any,
    absorption_score: Any,
) -> Dict[str, Any]:
    score_gap = round(score - entry_threshold, 4)

    return {
        "score_distance_to_threshold": score_gap,
        "stage_distance_to_threshold": None if stage is None else 0,
        "cq_distance_to_threshold": None if cq is None else 0,
        "mas_distance_to_threshold": None if mas is None else 0,
        "tes_distance_to_threshold": None if tes is None else 0,
        "mes_distance_to_threshold": None if mes is None else 0,
        "confidence_distance_to_threshold": None if confidence is None else 0,
        "absorption_distance_to_threshold": None if absorption_score is None else 0,
        "required_thresholds_note": f"Only score threshold ({entry_threshold}) is hard-enforced by live logic; other distances are informational when provided.",
        "direction": direction,
    }


def _extract_option_symbol(option_obj: Any) -> str | None:
    if isinstance(option_obj, dict):
        for key in ("symbol", "option_symbol", "contract", "description"):
            val = _safe_str(option_obj.get(key))
            if val:
                return val
        return _safe_str(json.dumps(option_obj, sort_keys=True))
    return _safe_str(option_obj)


def _build_setup_record(
    direction: str,
    evaluation_time_et: str,
    candle_time_et: str,
    spy_price: float,
    regime: str,
    score: int,
    reasons: List[str],
    entered: bool,
    allow_entry: bool,
    in_position: bool,
    in_market_hours: bool,
    entry_threshold: int,
    df,
    last,
    prev,
    feature_payload: Dict[str, Any],
    selected_option: Any,
) -> Dict[str, Any]:
    positives, penalties = _extract_positives_and_penalties(reasons)

    stage = _extract_snapshot_metric(feature_payload, direction, "trend_stage")
    cq = _extract_snapshot_metric(feature_payload, direction, "continuation_quality")
    mas = _extract_snapshot_metric(feature_payload, direction, "momentum_acceleration")
    tes = _extract_snapshot_metric(feature_payload, direction, "trend_efficiency_score")
    mes = _extract_snapshot_metric(feature_payload, direction, "micro_efficiency_score")
    confidence = _extract_snapshot_metric(feature_payload, direction, "confidence")
    absorption_score = _extract_snapshot_metric(feature_payload, direction, "absorption_score")

    if confidence is None:
        confidence = round((float(score) / max(float(entry_threshold), 1.0)) * 100.0, 2)

    rejection_reason = _direction_rejection_reason(
        direction=direction,
        entered=entered,
        allow_entry=allow_entry,
        in_position=in_position,
        in_market_hours=in_market_hours,
        regime=regime,
        score=score,
        entry_threshold=entry_threshold,
    )

    record = {
        "event_id": f"{candle_time_et}|{direction}",
        "evaluation_time_et": evaluation_time_et,
        "candle_time_et": candle_time_et,
        "direction": direction,
        "spy_price": spy_price,
        "option_selected": _extract_option_symbol(selected_option),
        "stage": stage,
        "cq": cq,
        "mas": mas,
        "tes": tes,
        "mes": mes,
        "confidence": confidence,
        "absorption_score": absorption_score,
        "positive_signals": positives,
        "penalties": penalties,
        "entered": bool(entered),
        "rejected": not bool(entered),
        "rejection_reason": rejection_reason,
        "market_regime": regime,
    }

    record.update(_build_threshold_distance_payload(
        direction=direction,
        score=score,
        entry_threshold=entry_threshold,
        stage=stage,
        cq=cq,
        mas=mas,
        tes=tes,
        mes=mes,
        confidence=confidence,
        absorption_score=absorption_score,
    ))

    record.update(_ema_metrics(df=df, last=last, bars=3))
    record.update(_macd_metrics(df=df, last=last, bars=3))
    record.update(_candle_structure(last=last, prev=prev, df=df))
    record.update(_candle_research_metrics(last=last, prev=prev, df=df))

    return record


def log_evaluated_setups(
    *,
    last,
    prev,
    df,
    regime: str,
    call_score: int,
    call_reasons: List[str],
    put_score: int,
    put_reasons: List[str],
    entry_threshold: int,
    allow_entry: bool,
    in_position: bool,
    in_market_hours: bool,
    entered_call: bool,
    entered_put: bool,
    feature_payload: Dict[str, Any] | None,
    selected_option_call: Any = None,
    selected_option_put: Any = None,
) -> None:
    payload = feature_payload or {}
    evaluation_time_et = datetime.now(EASTERN_TZ).isoformat()
    candle_time_et = _normalize_candle_time_to_et_iso(getattr(last, "name", None))
    spy_price = _safe_float(getattr(last, "close", None))
    if spy_price is None:
        return

    call_record = _build_setup_record(
        direction="CALL",
        evaluation_time_et=evaluation_time_et,
        candle_time_et=candle_time_et,
        spy_price=spy_price,
        regime=regime,
        score=int(call_score),
        reasons=list(call_reasons or []),
        entered=bool(entered_call),
        allow_entry=allow_entry,
        in_position=in_position,
        in_market_hours=in_market_hours,
        entry_threshold=entry_threshold,
        df=df,
        last=last,
        prev=prev,
        feature_payload=payload,
        selected_option=selected_option_call,
    )

    put_record = _build_setup_record(
        direction="PUT",
        evaluation_time_et=evaluation_time_et,
        candle_time_et=candle_time_et,
        spy_price=spy_price,
        regime=regime,
        score=int(put_score),
        reasons=list(put_reasons or []),
        entered=bool(entered_put),
        allow_entry=allow_entry,
        in_position=in_position,
        in_market_hours=in_market_hours,
        entry_threshold=entry_threshold,
        df=df,
        last=last,
        prev=prev,
        feature_payload=payload,
        selected_option=selected_option_put,
    )

    trade_date = datetime.fromisoformat(candle_time_et).date().isoformat()
    output_path = OPPORTUNITY_LOG_DIR / f"opportunity_setups_{trade_date}.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(call_record) + "\n")
        f.write(json.dumps(put_record) + "\n")
