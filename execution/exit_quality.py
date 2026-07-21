"""Read-only exit-quality calculations for completed option trades."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def executable_option_price(*, bid: Any = None, last: Any = None, mark: Any = None) -> tuple[float | None, str | None]:
    """Return the best attainable long-option exit price and its source."""
    for source, value in (("bid", bid), ("last", last), ("mark", mark)):
        price = _positive_float(value)
        if price is not None:
            return price, source
    return None, None


def update_option_extrema(position: Any, *, spy_price: Any, bid: Any = None, last: Any = None, mark: Any = None, observed_at: datetime | None = None) -> bool:
    """Update persisted option extrema from one executable quote observation."""
    option_price, _ = executable_option_price(bid=bid, last=last, mark=mark)
    if option_price is None:
        return False

    timestamp = (observed_at or datetime.now()).isoformat()
    spy_value = _positive_float(spy_price)
    high = _positive_float(getattr(position, "option_high_since_entry", None))
    low = _positive_float(getattr(position, "option_low_since_entry", None))

    changed = False
    if high is None or option_price > high:
        position.option_high_since_entry = option_price
        position.option_high_timestamp = timestamp
        position.spy_price_at_option_high = spy_value
        changed = True
    if low is None or option_price < low:
        position.option_low_since_entry = option_price
        position.option_low_timestamp = timestamp
        position.spy_price_at_option_low = spy_value
        changed = True
    return changed


def exit_quality_metrics(*, option_entry: Any, option_exit: Any, option_high: Any, option_low: Any, quantity: Any, entry_time: Any, exit_time: Any, high_timestamp: Any) -> dict[str, float | None]:
    """Calculate post-trade excursion and peak-capture metrics without policy inputs."""
    entry = _positive_float(option_entry)
    exit_price = _positive_float(option_exit)
    high = _positive_float(option_high)
    low = _positive_float(option_low)
    if entry is None or exit_price is None or high is None or low is None:
        return {
            "mfe_pct": None, "mae_pct": None, "exit_efficiency_pct": None,
            "peak_capture_pct": None, "profit_left_on_table_dollars": None,
            "minutes_to_peak": None, "minutes_after_peak_until_exit": None,
        }

    mfe_pct = ((high - entry) / entry) * 100.0
    mae_pct = ((low - entry) / entry) * 100.0
    realized_pct = ((exit_price - entry) / entry) * 100.0
    excursion_range = mfe_pct - mae_pct
    exit_efficiency_pct = ((realized_pct - mae_pct) / excursion_range) * 100.0 if excursion_range > 0 else None
    peak_capture_pct = (realized_pct / mfe_pct) * 100.0 if mfe_pct > 0 else None

    try:
        contracts = max(0.0, float(quantity or 0))
    except (TypeError, ValueError):
        contracts = 0.0
    profit_left = max(0.0, high - exit_price) * contracts * 100.0

    def _parse(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            return None

    opened = _parse(entry_time)
    closed = _parse(exit_time)
    peaked = _parse(high_timestamp)
    minutes_to_peak = ((peaked - opened).total_seconds() / 60.0) if opened and peaked else None
    minutes_after_peak = ((closed - peaked).total_seconds() / 60.0) if closed and peaked else None

    return {
        "mfe_pct": round(mfe_pct, 4),
        "mae_pct": round(mae_pct, 4),
        "exit_efficiency_pct": round(exit_efficiency_pct, 4) if exit_efficiency_pct is not None else None,
        "peak_capture_pct": round(peak_capture_pct, 4) if peak_capture_pct is not None else None,
        "profit_left_on_table_dollars": round(profit_left, 4),
        "minutes_to_peak": round(minutes_to_peak, 4) if minutes_to_peak is not None else None,
        "minutes_after_peak_until_exit": round(minutes_after_peak, 4) if minutes_after_peak is not None else None,
    }
