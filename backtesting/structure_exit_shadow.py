"""Shadow-only structure-stop simulations for exit-policy research.

This module does not participate in live or paper trade management. It uses
completed SPY candles to compare deterministic structure exits on an identical
opportunity path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd


StructureExitPolicy = Literal["SWING_2", "SWING_3"]


@dataclass(frozen=True)
class StructureExitResult:
    """A reproducible result for one shadow structure-exit policy."""

    policy_id: str
    direction: str
    entry_spy_price: float
    entry_option_price: float
    exit_spy_price: float
    exit_option_price: float
    exit_index: int
    exit_reason: str
    active_structure_stop: float | None
    realized_r: float | None
    peak_capture_pct: float | None
    exit_efficiency_pct: float | None


def _option_price(pricer: Any, *, direction: str, entry_spy_price: float, entry_time: Any, current_time: Any, current_spy_price: float) -> float:
    if hasattr(pricer, "get_option_mark_and_bid"):
        mark, bid, _source = pricer.get_option_mark_and_bid(
            direction=direction,
            entry_spy_price=entry_spy_price,
            current_spy_price=current_spy_price,
            entry_time=entry_time,
            current_time=current_time,
        )
        return float(bid or mark)
    return float(
        pricer.simulate_price_change(
            direction=direction,
            entry_spy_price=entry_spy_price,
            current_spy_price=current_spy_price,
            entry_time=entry_time,
            current_time=current_time,
            position="bid",
        )
    )


def simulate_structure_exit_shadow(
    *,
    candles: pd.DataFrame,
    direction: str,
    entry_spy_price: float,
    entry_option_price: float,
    entry_time: Any,
    pricer: Any,
    policy_id: StructureExitPolicy,
    initial_option_stop: float,
) -> StructureExitResult:
    """Simulate one completed-candle swing-stop policy without live side effects.

    A structure stop is armed only after the option is profitable. For Calls it
    ratchets to the highest available low of the prior ``N`` completed candles;
    for Puts it ratchets to the lowest available high. The current candle's
    close then determines whether the already-armed stop is invalidated.
    """
    normalized_direction = str(direction or "").upper()
    if normalized_direction not in {"CALL", "PUT"}:
        raise ValueError(f"Unsupported direction: {direction!r}")
    if policy_id not in {"SWING_2", "SWING_3"}:
        raise ValueError(f"Unsupported structure policy: {policy_id!r}")
    required = {"timestamp", "high", "low", "close"}
    if candles is None or candles.empty or not required.issubset(candles.columns):
        raise ValueError("candles must contain timestamp, high, low, and close")
    if entry_option_price <= 0 or initial_option_stop <= 0:
        raise ValueError("entry_option_price and initial_option_stop must be positive")

    window = int(policy_id.rsplit("_", 1)[1])
    ordered = candles.sort_values("timestamp").reset_index(drop=True)
    active_structure_stop: float | None = None
    option_prices: list[float] = []
    exit_index = len(ordered) - 1
    exit_reason = "SHADOW_WINDOW_END"

    for index, candle in ordered.iterrows():
        close = float(candle["close"])
        option_price = _option_price(
            pricer,
            direction=normalized_direction,
            entry_spy_price=float(entry_spy_price),
            entry_time=entry_time,
            current_time=candle["timestamp"],
            current_spy_price=close,
        )
        option_prices.append(option_price)

        # The unchanged live initial option-risk floor applies before structure arms.
        if option_price <= float(initial_option_stop):
            exit_index = index
            exit_reason = "SHADOW_INITIAL_OPTION_STOP"
            break

        if option_price > float(entry_option_price) and index >= window:
            prior = ordered.iloc[index - window:index]
            candidate = float(prior["low"].min()) if normalized_direction == "CALL" else float(prior["high"].max())
            if active_structure_stop is None:
                active_structure_stop = candidate
            elif normalized_direction == "CALL":
                active_structure_stop = max(active_structure_stop, candidate)
            else:
                active_structure_stop = min(active_structure_stop, candidate)

        if active_structure_stop is not None:
            invalidated = close <= active_structure_stop if normalized_direction == "CALL" else close >= active_structure_stop
            if invalidated:
                exit_index = index
                exit_reason = f"SHADOW_{policy_id}_STRUCTURE_STOP"
                break

    exit_spy_price = float(ordered.iloc[exit_index]["close"])
    exit_option_price = float(option_prices[exit_index])
    peak_option = max(option_prices) if normalized_direction == "CALL" else max(option_prices)
    trough_option = min(option_prices)
    risk_per_option = float(entry_option_price) - float(initial_option_stop)
    realized_r = (exit_option_price - float(entry_option_price)) / risk_per_option if risk_per_option > 0 else None
    mfe = peak_option - float(entry_option_price)
    mae = trough_option - float(entry_option_price)
    peak_capture_pct = ((exit_option_price - float(entry_option_price)) / mfe * 100.0) if mfe > 0 else None
    excursion_range = mfe - mae
    exit_efficiency_pct = ((exit_option_price - trough_option) / excursion_range * 100.0) if excursion_range > 0 else None

    return StructureExitResult(
        policy_id=policy_id,
        direction=normalized_direction,
        entry_spy_price=float(entry_spy_price),
        entry_option_price=float(entry_option_price),
        exit_spy_price=exit_spy_price,
        exit_option_price=exit_option_price,
        exit_index=exit_index,
        exit_reason=exit_reason,
        active_structure_stop=active_structure_stop,
        realized_r=round(realized_r, 6) if realized_r is not None else None,
        peak_capture_pct=round(peak_capture_pct, 4) if peak_capture_pct is not None else None,
        exit_efficiency_pct=round(exit_efficiency_pct, 4) if exit_efficiency_pct is not None else None,
    )