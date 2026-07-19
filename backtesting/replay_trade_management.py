"""Shared replay trade-management logic used across backtesting tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dt_time
from typing import Optional, Any

import pandas as pd

from backtesting.option_pricer import EstimatedOptionPricer


@dataclass
class ReplayTradeManagementState:
    entry_time: datetime
    direction: str
    entry_spy_price: float
    entry_option_price: float
    initial_stop: float
    active_stop: float
    peak_option_price: float
    breakeven_armed: bool


@dataclass
class ReplayTradeStepResult:
    option_mark: float
    option_bid: float
    price_source: str
    stop_evaluation_price: float
    option_pnl_pct: float
    peak_option_price_before_update: float
    peak_option_price_after_update: float
    active_stop_before_update: float
    active_stop_after_update: float
    trailing_percentage: Optional[float]
    trailing_active: bool
    exit_decision: str
    exit_reason: str
    final_option_price: float
    stop_check_order: str
    stop_comparison: str
    max_hold_comparison: str
    eod_comparison: str


def run_deterministic_trade_replay(
    *,
    candles: pd.DataFrame,
    state: ReplayTradeManagementState,
    pricer: EstimatedOptionPricer,
    eod_exit_time: dt_time,
    max_hold_minutes: int,
) -> pd.DataFrame:
    """Run deterministic replay across a fixed candle sequence.

    The input candles must contain: timestamp, open, high, low, close.
    Returns a canonical minute-by-minute trace used by inspector and validation.
    """
    rows = []
    exited = False

    for _, candle in candles.iterrows():
        ts = candle["timestamp"]
        if exited:
            break

        close_px = float(candle["close"])
        step = evaluate_trade_management_step(
            state=state,
            pricer=pricer,
            current_spy_price=close_px,
            current_time=ts,
            eod_exit_time=eod_exit_time,
            max_hold_minutes=max_hold_minutes,
        )

        rows.append(
            {
                "timestamp": ts,
                "spy_open": float(candle["open"]),
                "spy_high": float(candle["high"]),
                "spy_low": float(candle["low"]),
                "spy_close": close_px,
                "option_mark": float(step.option_mark),
                "option_bid": float(step.option_bid),
                "price_source": str(step.price_source),
                "option_pnl_pct": float(step.option_pnl_pct),
                "peak_before": float(step.peak_option_price_before_update),
                "peak_after": float(step.peak_option_price_after_update),
                "original_stop": float(state.initial_stop),
                "stop_before": float(step.active_stop_before_update),
                "stop_after": float(step.active_stop_after_update),
                "breakeven_armed": bool(state.breakeven_armed),
                "trailing_active": bool(step.trailing_active),
                "trailing_tier": step.trailing_percentage if step.trailing_percentage is not None else "",
                "stop_eval_price": float(step.stop_evaluation_price),
                "stop_comparison": step.stop_comparison,
                "max_hold_comparison": step.max_hold_comparison,
                "eod_comparison": step.eod_comparison,
                "exit_decision": step.exit_decision,
                "exit_reason": step.exit_reason,
                "final_option_price": float(step.final_option_price),
            }
        )

        if step.exit_decision == "EXIT":
            exited = True

    return pd.DataFrame(rows)


def _active_trailing_pct(option_pnl_pct: float) -> Optional[float]:
    if option_pnl_pct >= 25.0:
        return 1.5
    if option_pnl_pct >= 15.0:
        return 2.0
    if option_pnl_pct >= 8.0:
        return 3.0
    return None


def initialize_trade_management_state(
    *,
    entry_time: datetime,
    direction: str,
    entry_spy_price: float,
    entry_option_price: float,
) -> ReplayTradeManagementState:
    initial_stop = float(entry_option_price * 0.95)
    return ReplayTradeManagementState(
        entry_time=entry_time,
        direction=direction,
        entry_spy_price=float(entry_spy_price),
        entry_option_price=float(entry_option_price),
        initial_stop=initial_stop,
        active_stop=initial_stop,
        peak_option_price=float(entry_option_price),
        breakeven_armed=False,
    )


def evaluate_trade_management_step(
    *,
    state: ReplayTradeManagementState,
    pricer: Any,
    current_spy_price: float,
    current_time: datetime,
    eod_exit_time: dt_time,
    max_hold_minutes: int,
) -> ReplayTradeStepResult:
    peak_before_update = float(state.peak_option_price)
    active_stop_before_update = float(state.active_stop)

    if hasattr(pricer, "get_option_mark_and_bid"):
        option_mark, option_bid, price_source = pricer.get_option_mark_and_bid(
            direction=state.direction,
            entry_spy_price=state.entry_spy_price,
            current_spy_price=float(current_spy_price),
            entry_time=state.entry_time,
            current_time=current_time,
        )
        option_mark = float(option_mark)
        option_bid = float(option_bid)
        price_source = str(price_source)
    else:
        option_mark = float(
            pricer.simulate_price_change(
                direction=state.direction,
                entry_spy_price=state.entry_spy_price,
                current_spy_price=float(current_spy_price),
                entry_time=state.entry_time,
                current_time=current_time,
                position="mid",
            )
        )
        option_bid = float(pricer.get_bid_ask_adjusted_price(option_mark, side="bid"))
        price_source = "ESTIMATED"
    stop_evaluation_price = option_bid if option_bid > 0 else option_mark

    eod_hit = current_time.time() >= eod_exit_time
    eod_comparison = f"{current_time.time()} >= {eod_exit_time}"

    hold_minutes = (current_time - state.entry_time).total_seconds() / 60.0
    max_hold_hit = hold_minutes >= float(max_hold_minutes)
    max_hold_comparison = f"{round(hold_minutes, 6)} >= {float(max_hold_minutes)}"

    if eod_hit:
        return ReplayTradeStepResult(
            option_mark=option_mark,
            option_bid=option_bid,
            price_source=price_source,
            stop_evaluation_price=stop_evaluation_price,
            option_pnl_pct=0.0,
            peak_option_price_before_update=peak_before_update,
            peak_option_price_after_update=float(state.peak_option_price),
            active_stop_before_update=active_stop_before_update,
            active_stop_after_update=float(state.active_stop),
            trailing_percentage=None,
            trailing_active=False,
            exit_decision="EXIT",
            exit_reason="END_OF_DAY_EXIT",
            final_option_price=option_mark,
            stop_check_order="AFTER_PRICE_UPDATE",
            stop_comparison=f"{round(stop_evaluation_price, 6)} <= {round(state.active_stop, 6)}",
            max_hold_comparison=max_hold_comparison,
            eod_comparison=eod_comparison,
        )

    if max_hold_hit:
        return ReplayTradeStepResult(
            option_mark=option_mark,
            option_bid=option_bid,
            price_source=price_source,
            stop_evaluation_price=stop_evaluation_price,
            option_pnl_pct=0.0,
            peak_option_price_before_update=peak_before_update,
            peak_option_price_after_update=float(state.peak_option_price),
            active_stop_before_update=active_stop_before_update,
            active_stop_after_update=float(state.active_stop),
            trailing_percentage=None,
            trailing_active=False,
            exit_decision="EXIT",
            exit_reason="MAX_HOLD_15_MIN",
            final_option_price=option_mark,
            stop_check_order="AFTER_PRICE_UPDATE",
            stop_comparison=f"{round(stop_evaluation_price, 6)} <= {round(state.active_stop, 6)}",
            max_hold_comparison=max_hold_comparison,
            eod_comparison=eod_comparison,
        )

    if option_mark > state.peak_option_price:
        state.peak_option_price = option_mark

    option_pnl_pct = (
        (option_mark - state.entry_option_price) / state.entry_option_price * 100.0
        if state.entry_option_price > 0
        else 0.0
    )

    if option_pnl_pct >= 5.0:
        state.breakeven_armed = True
        state.active_stop = max(state.active_stop, state.entry_option_price)

    trailing_percentage = _active_trailing_pct(option_pnl_pct)
    if trailing_percentage is not None:
        trailing_stop = option_mark * (1.0 - trailing_percentage / 100.0)
        state.active_stop = max(state.active_stop, trailing_stop)

    peak_after_update = float(state.peak_option_price)
    active_stop_after_update = float(state.active_stop)
    stop_comparison = f"{round(stop_evaluation_price, 6)} <= {round(state.active_stop, 6)}"

    if stop_evaluation_price <= state.active_stop:
        if state.active_stop > state.initial_stop and option_pnl_pct > 0:
            exit_reason = "TRAILING_STOP"
        else:
            exit_reason = "INITIAL_STOP"
        return ReplayTradeStepResult(
            option_mark=option_mark,
            option_bid=option_bid,
            price_source=price_source,
            stop_evaluation_price=stop_evaluation_price,
            option_pnl_pct=option_pnl_pct,
            peak_option_price_before_update=peak_before_update,
            peak_option_price_after_update=peak_after_update,
            active_stop_before_update=active_stop_before_update,
            active_stop_after_update=active_stop_after_update,
            trailing_percentage=trailing_percentage,
            trailing_active=trailing_percentage is not None,
            exit_decision="EXIT",
            exit_reason=exit_reason,
            final_option_price=stop_evaluation_price,
            stop_check_order="AFTER_PRICE_UPDATE",
            stop_comparison=stop_comparison,
            max_hold_comparison=max_hold_comparison,
            eod_comparison=eod_comparison,
        )

    return ReplayTradeStepResult(
        option_mark=option_mark,
        option_bid=option_bid,
        price_source=price_source,
        stop_evaluation_price=stop_evaluation_price,
        option_pnl_pct=option_pnl_pct,
        peak_option_price_before_update=peak_before_update,
        peak_option_price_after_update=peak_after_update,
        active_stop_before_update=active_stop_before_update,
        active_stop_after_update=active_stop_after_update,
        trailing_percentage=trailing_percentage,
        trailing_active=trailing_percentage is not None,
        exit_decision="HOLD",
        exit_reason="",
        final_option_price=option_mark,
        stop_check_order="AFTER_PRICE_UPDATE",
        stop_comparison=stop_comparison,
        max_hold_comparison=max_hold_comparison,
        eod_comparison=eod_comparison,
    )
