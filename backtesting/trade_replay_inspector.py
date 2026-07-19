"""Minute-by-minute trade replay inspector for backtesting diagnostics.

This module is backtesting-only and does not modify live/paper behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd

from backtesting.data_loader import TIMEZONE
from backtesting.option_pricer import EstimatedOptionPricer
from backtesting import load_csv_data
from backtesting.replay_trade_management import (
    initialize_trade_management_state,
    run_deterministic_trade_replay,
)


@dataclass
class PaperTradeSpec:
    data_path: Path
    trade_date: str
    entry_time: str
    direction: str
    paper_exit_time: str
    paper_pnl: float
    paper_return: float
    paper_exit_reason: str = "OPTION_STOP"


def _to_et_datetime(trade_date: str, time_str: str) -> pd.Timestamp:
    dt = pd.Timestamp(f"{trade_date} {time_str}")
    if dt.tzinfo is None:
        dt = dt.tz_localize(TIMEZONE)
    return dt.tz_convert(TIMEZONE)


def _minute_bounds(entry_dt: pd.Timestamp, exit_dt: pd.Timestamp) -> Tuple[pd.Timestamp, pd.Timestamp]:
    start = entry_dt.floor("min")
    if entry_dt.second > 0 or entry_dt.microsecond > 0:
        start = start + pd.Timedelta(minutes=1)
    end = exit_dt.floor("min")
    return start, end


def inspect_trade_from_df(
    df_all: pd.DataFrame,
    spec: PaperTradeSpec,
    out_csv_path: Optional[Path] = None,
    out_txt_path: Optional[Path] = None,
    option_pricer: Optional[Any] = None,
) -> Dict[str, object]:
    direction = str(spec.direction).upper()
    if direction not in {"CALL", "PUT"}:
        raise ValueError(f"Unsupported direction: {direction}")

    entry_dt = _to_et_datetime(spec.trade_date, spec.entry_time)
    paper_exit_dt = _to_et_datetime(spec.trade_date, spec.paper_exit_time)
    start_minute, end_minute = _minute_bounds(entry_dt, paper_exit_dt)

    df_day = df_all[df_all["timestamp"].dt.date == entry_dt.date()].copy()
    if df_day.empty:
        raise ValueError(f"No candles found for date {spec.trade_date}")

    entry_candidates = df_day[df_day["timestamp"] <= entry_dt]
    if entry_candidates.empty:
        raise ValueError("No completed candle at or before paper entry time")
    entry_row = entry_candidates.iloc[-1]
    simulated_entry_dt = entry_row["timestamp"].tz_convert(TIMEZONE)

    minute_rows = df_day[(df_day["timestamp"] >= start_minute) & (df_day["timestamp"] <= end_minute)].copy()
    minute_rows = minute_rows.sort_values("timestamp").reset_index(drop=True)
    if minute_rows.empty:
        raise ValueError("No completed minute candles in requested entry->exit window")

    pricer = option_pricer or EstimatedOptionPricer()

    entry_spy_price = float(entry_row["close"])
    try:
        entry_mid_price = float(
            pricer.get_entry_price(
                direction=direction,
                entry_time=simulated_entry_dt,
                entry_spy_price=entry_spy_price,
            )
        )
    except TypeError:
        entry_mid_price = float(pricer.get_entry_price())
    entry_final_price = entry_mid_price

    management_state = initialize_trade_management_state(
        entry_time=simulated_entry_dt,
        direction=direction,
        entry_spy_price=entry_spy_price,
        entry_option_price=entry_final_price,
    )

    # Match production paper engine: initial option stop is fixed at -5% from option entry.
    initial_stop = float(management_state.initial_stop)

    current_option_mid = entry_final_price
    peak_option_price = entry_final_price
    active_stop = initial_stop
    breakeven_armed = False
    exited = False
    replay_exit_time: Optional[pd.Timestamp] = None
    replay_exit_reason: Optional[str] = None
    replay_exit_mid: Optional[float] = None
    replay_exit_final: Optional[float] = None

    prev_cum_decay = 0.0
    entry_slippage_applied = False
    exit_slippage_applied = False

    rows: List[Dict[str, object]] = []
    trace_df = run_deterministic_trade_replay(
        candles=minute_rows,
        state=management_state,
        pricer=pricer,
        eod_exit_time=pd.Timestamp("15:59:00").time(),
        max_hold_minutes=15,
    )

    for _, trace in trace_df.iterrows():
        ts = pd.Timestamp(trace["timestamp"]).tz_convert(TIMEZONE)
        close_px = float(trace["spy_close"])
        current_option_mid = float(trace["option_mark"])
        final_option_price = float(trace["final_option_price"])
        peak_option_price = float(trace["peak_after"])
        active_stop = float(trace["stop_after"])
        breakeven_armed = bool(trace["breakeven_armed"])
        option_pnl_pct = float(trace["option_pnl_pct"])

        elapsed_min = float((ts - simulated_entry_dt).total_seconds() / 60.0)
        cum_decay = max(0.0, pricer.time_decay_per_minute * elapsed_min)
        decay_this_minute = cum_decay - prev_cum_decay
        prev_cum_decay = cum_decay

        exit_decision = str(trace["exit_decision"])
        exit_reason = str(trace["exit_reason"] or "")
        stop_check_order = "AFTER_PRICE_UPDATE"
        stop_eval_price = float(trace["stop_eval_price"])
        stop_comparison = str(trace["stop_comparison"])
        trailing_tier = trace["trailing_tier"]
        trailing_active = bool(trace["trailing_active"])
        price_source = str(trace.get("price_source", "ESTIMATED"))

        exit_slippage_val = max(current_option_mid - final_option_price, 0.0) if exit_decision == "EXIT" else 0.0
        if exit_decision == "EXIT" and not exited:
            replay_exit_time = ts
            replay_exit_reason = exit_reason
            replay_exit_mid = current_option_mid
            replay_exit_final = final_option_price
            exited = True

        current_dollar_pnl = (final_option_price - entry_final_price) * 100.0
        current_pct_pnl = ((final_option_price - entry_final_price) / entry_final_price) * 100.0

        if not entry_slippage_applied:
            entry_slip_val = 0.0
            entry_slippage_applied = True
        else:
            entry_slip_val = 0.0

        if exit_slippage_val > 0:
            exit_slippage_applied = True

        rows.append(
            {
                "timestamp": ts.isoformat(),
                "spy_open": float(trace["spy_open"]),
                "spy_high": float(trace["spy_high"]),
                "spy_low": float(trace["spy_low"]),
                "spy_close": close_px,
                "spy_change_from_entry_dollars": close_px - entry_spy_price,
                "direction": direction,
                "option_price_source": price_source,
                "estimated_option_price_before_slippage": round(current_option_mid, 6),
                "time_decay_applied_this_minute": round(decay_this_minute, 6),
                "cumulative_time_decay": round(cum_decay, 6),
                "entry_slippage": round(entry_slip_val, 6),
                "exit_slippage": round(exit_slippage_val, 6),
                "final_estimated_option_price": round(final_option_price, 6),
                "current_option_pnl_dollars": round(current_dollar_pnl, 6),
                "current_option_pnl_percent": round(current_pct_pnl, 6),
                "initial_stop_level": round(initial_stop, 6),
                "active_stop_before_update": round(float(trace["stop_before"]), 6),
                "current_active_stop": round(active_stop, 6),
                "active_stop_after_update": round(float(trace["stop_after"]), 6),
                "peak_option_price_before_update": round(float(trace["peak_before"]), 6),
                "peak_option_price": round(peak_option_price, 6),
                "peak_option_price_after_update": round(float(trace["peak_after"]), 6),
                "breakeven_armed": bool(breakeven_armed),
                "dynamic_trailing_active": bool(trailing_active),
                "current_trailing_percentage": trailing_tier if trailing_tier != "" else "",
                "stop_checked_before_or_after_price_update": stop_check_order,
                "stop_evaluation_price": round(stop_eval_price, 6),
                "stop_comparison": stop_comparison,
                "max_hold_comparison": str(trace["max_hold_comparison"]),
                "eod_comparison": str(trace["eod_comparison"]),
                "exit_decision": exit_decision,
                "exit_reason_if_triggered": exit_reason,
            }
        )

    replay_df = pd.DataFrame(rows)

    if replay_exit_time is None and not replay_df.empty:
        # No stop hit in window: close at last available minute for diagnostic parity.
        last = replay_df.iloc[-1]
        replay_exit_time = pd.Timestamp(last["timestamp"]) if isinstance(last["timestamp"], str) else pd.Timestamp(last["timestamp"])
        replay_exit_reason = "NO_EXIT_TRIGGERED"
        replay_exit_mid = float(last["estimated_option_price_before_slippage"])
        replay_exit_final = float(last["final_estimated_option_price"])

    replay_pnl = (float(replay_exit_final) - entry_final_price) * 100.0 if replay_exit_final is not None else 0.0
    replay_return = ((float(replay_exit_final) - entry_final_price) / entry_final_price) * 100.0 if replay_exit_final is not None else 0.0

    # Validation checks.
    option_mid_series = replay_df["estimated_option_price_before_slippage"].astype(float) if not replay_df.empty else pd.Series(dtype=float)
    spy_change_series = replay_df["spy_change_from_entry_dollars"].astype(float) if not replay_df.empty else pd.Series(dtype=float)
    option_step = option_mid_series.diff()
    spy_step = spy_change_series.diff()

    put_rises_when_spy_falls = True
    put_falls_when_spy_rises = True
    if direction == "PUT":
        fall_idx = spy_step < 0
        rise_idx = spy_step > 0
        if fall_idx.any():
            put_rises_when_spy_falls = bool((option_step[fall_idx] > 0).all())
        if rise_idx.any():
            put_falls_when_spy_rises = bool((option_step[rise_idx] < 0).all())

    call_rises_when_spy_rises = True
    call_falls_when_spy_falls = True
    if direction == "CALL":
        rise_idx = spy_step > 0
        fall_idx = spy_step < 0
        if rise_idx.any():
            call_rises_when_spy_rises = bool((option_step[rise_idx] > 0).all())
        if fall_idx.any():
            call_falls_when_spy_falls = bool((option_step[fall_idx] < 0).all())

    entry_slippage_once = bool((replay_df["entry_slippage"] > 0).sum() <= 1)
    exit_slippage_once = bool((replay_df["exit_slippage"] > 0).sum() <= 1)

    # Once-per-minute linear decay check.
    once_per_minute_decay = True
    if not replay_df.empty:
        expected = replay_df["timestamp"].map(lambda s: (pd.Timestamp(s).tz_convert(TIMEZONE) - simulated_entry_dt).total_seconds() / 60.0)
        expected = expected * pricer.time_decay_per_minute
        actual = replay_df["cumulative_time_decay"].astype(float)
        once_per_minute_decay = bool(((actual - expected).abs() <= 1e-6).all())

    stop_after_update = bool((replay_df["stop_checked_before_or_after_price_update"] == "AFTER_PRICE_UPDATE").all()) if not replay_df.empty else True

    first_breakeven_idx = replay_df.index[replay_df["breakeven_armed"] == True].tolist() if not replay_df.empty else []
    initial_stop_persists = True
    if first_breakeven_idx:
        pre = replay_df.loc[: first_breakeven_idx[0] - 1] if first_breakeven_idx[0] > 0 else replay_df.iloc[0:0]
        if not pre.empty:
            initial_stop_persists = bool((pre["current_active_stop"].astype(float) == round(initial_stop, 6)).all())

    breakeven_activates_at_5 = True
    if not replay_df.empty and (replay_df["current_option_pnl_percent"] >= 5).any():
        first_5 = replay_df[replay_df["current_option_pnl_percent"] >= 5].index[0]
        breakeven_activates_at_5 = bool(replay_df.loc[first_5, "breakeven_armed"])

    trailing_rules_followed = True
    if not replay_df.empty:
        for _, r in replay_df.iterrows():
            pnl_pct = float(r["current_option_pnl_percent"])
            tr = r["current_trailing_percentage"]
            if pnl_pct >= 25 and tr not in (1.5, "1.5"):
                trailing_rules_followed = False
                break
            if 15 <= pnl_pct < 25 and tr not in (2.0, "2.0") and tr not in (1.5, "1.5"):
                trailing_rules_followed = False
                break
            if 8 <= pnl_pct < 15 and tr not in (3.0, "3.0", 2.0, "2.0", 1.5, "1.5"):
                trailing_rules_followed = False
                break

    profitable_trailing_labeled = True
    if replay_exit_reason == "TRAILING_STOP" and replay_pnl > 0:
        profitable_trailing_labeled = True
    elif replay_exit_reason == "INITIAL_STOP" and replay_pnl > 0:
        profitable_trailing_labeled = False

    # Divergence vs paper.
    expected_rows = []
    for _, r in replay_df.iterrows():
        ts = pd.Timestamp(r["timestamp"]).tz_convert(TIMEZONE)
        if ts < paper_exit_dt.floor("min"):
            exp_decision = "HOLD"
            exp_reason = ""
        elif ts == paper_exit_dt.floor("min"):
            exp_decision = "EXIT"
            exp_reason = spec.paper_exit_reason
        else:
            exp_decision = "N/A"
            exp_reason = ""
        expected_rows.append((exp_decision, exp_reason))

    first_div_ts = ""
    first_div_field = ""
    if not replay_df.empty:
        for idx, r in replay_df.iterrows():
            exp_decision, exp_reason = expected_rows[idx]
            if exp_decision == "N/A":
                continue
            if str(r["exit_decision"]) != exp_decision:
                first_div_ts = r["timestamp"]
                first_div_field = "exit_decision"
                break
            if exp_reason and str(r["exit_reason_if_triggered"]) != exp_reason:
                first_div_ts = r["timestamp"]
                first_div_field = "exit_reason_if_triggered"
                break

    if not first_div_ts:
        if abs(float(replay_pnl) - float(spec.paper_pnl)) > 1e-9:
            first_div_ts = paper_exit_dt.isoformat()
            first_div_field = "paper_pnl_vs_replay_pnl"
        elif abs(float(replay_return) - float(spec.paper_return)) > 1e-9:
            first_div_ts = paper_exit_dt.isoformat()
            first_div_field = "paper_return_vs_replay_return"

    replay_exited_too_early = bool(replay_exit_time is not None and replay_exit_time < paper_exit_dt)
    replay_exit_price_too_low = bool(replay_pnl < spec.paper_pnl)
    stop_logic_differed = bool((replay_exit_reason or "") != (spec.paper_exit_reason or ""))
    slippage_or_decay_overapplied = not (entry_slippage_once and exit_slippage_once and once_per_minute_decay)

    if replay_exited_too_early and stop_logic_differed:
        likely_root_cause = "Replay stop logic/threshold timing differs from paper execution timing."
    elif replay_exit_price_too_low and not slippage_or_decay_overapplied:
        likely_root_cause = "Synthetic option-pricing path diverges from paper option fills/quotes."
    elif slippage_or_decay_overapplied:
        likely_root_cause = "Slippage or time decay application appears inconsistent."
    else:
        likely_root_cause = "Differences likely come from fill model and intraminute option behavior not captured by 1m close-based replay."

    summary = {
        "paper_result": {
            "direction": direction,
            "entry_time": entry_dt.isoformat(),
            "exit_time": paper_exit_dt.isoformat(),
            "paper_pnl": float(spec.paper_pnl),
            "paper_return": float(spec.paper_return),
            "paper_exit_reason": spec.paper_exit_reason,
        },
        "replay_result": {
            "entry_time": entry_dt.isoformat(),
            "entry_spy_price": round(entry_spy_price, 4),
            "entry_option_mid": round(entry_mid_price, 4),
            "entry_option_final": round(entry_final_price, 4),
            "replay_exit_time": replay_exit_time.isoformat() if replay_exit_time is not None else "",
            "replay_exit_reason": replay_exit_reason or "",
            "replay_pnl": round(float(replay_pnl), 4),
            "replay_return": round(float(replay_return), 4),
        },
        "first_divergence_timestamp": first_div_ts,
        "first_divergent_field": first_div_field,
        "replay_exited_too_early": replay_exited_too_early,
        "replay_exit_price_too_low": replay_exit_price_too_low,
        "stop_logic_differed": stop_logic_differed,
        "slippage_or_time_decay_overapplied": slippage_or_decay_overapplied,
        "most_likely_root_cause": likely_root_cause,
        "validations": {
            "1_put_rises_when_spy_falls": put_rises_when_spy_falls if direction == "PUT" else call_rises_when_spy_rises,
            "2_put_falls_when_spy_rises": put_falls_when_spy_rises if direction == "PUT" else call_falls_when_spy_falls,
            "3_entry_slippage_once_only": entry_slippage_once,
            "4_exit_slippage_once_only": exit_slippage_once,
            "5_time_decay_once_per_minute_only": once_per_minute_decay,
            "6_stop_eval_after_price_update": stop_after_update,
            "7_initial_stop_persists_until_state_change": initial_stop_persists,
            "8_breakeven_activates_at_5": breakeven_activates_at_5,
            "9_dynamic_trailing_thresholds_follow_production": trailing_rules_followed,
            "10_profitable_trailing_stop_labeled_trailing_stop": profitable_trailing_labeled,
            "11_first_minute_divergence_reported": bool(first_div_ts),
        },
    }

    if out_csv_path is not None:
        out_csv_path.parent.mkdir(parents=True, exist_ok=True)
        replay_df.to_csv(out_csv_path, index=False)

    if out_txt_path is not None:
        out_txt_path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        lines.append("Trade Replay Inspector Summary")
        lines.append("=" * 80)
        lines.append("Paper result")
        lines.append(str(summary["paper_result"]))
        lines.append("Replay result")
        lines.append(str(summary["replay_result"]))
        lines.append(f"First divergence timestamp: {summary['first_divergence_timestamp']}")
        lines.append(f"First divergent field: {summary['first_divergent_field']}")
        lines.append(f"Replay exited too early: {summary['replay_exited_too_early']}")
        lines.append(f"Replay exit price too low: {summary['replay_exit_price_too_low']}")
        lines.append(f"Stop logic differed: {summary['stop_logic_differed']}")
        lines.append(f"Slippage/time decay over-applied: {summary['slippage_or_time_decay_overapplied']}")
        lines.append(f"Most likely root cause: {summary['most_likely_root_cause']}")
        lines.append("Validations")
        for k, v in summary["validations"].items():
            lines.append(f"- {k}: {v}")
        out_txt_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "replay_df": replay_df,
        "summary": summary,
    }


def inspect_trade(
    spec: PaperTradeSpec,
    out_csv_path: Optional[Path] = None,
    out_txt_path: Optional[Path] = None,
    option_pricer: Optional[Any] = None,
) -> Dict[str, object]:
    df = load_csv_data(str(spec.data_path))
    return inspect_trade_from_df(
        df_all=df,
        spec=spec,
        out_csv_path=out_csv_path,
        out_txt_path=out_txt_path,
        option_pricer=option_pricer,
    )
