"""Broker-neutral policy helpers consumed by Cockpit status views."""

from __future__ import annotations


def active_stop_category(option_entry, current_mark=None, stop_price=None):
    """Map an option position into the canonical stop ladder."""
    try:
        option_entry = float(option_entry or 0.0)
    except (TypeError, ValueError):
        option_entry = 0.0
    if option_entry <= 0:
        return None

    try:
        current_mark = float(current_mark) if current_mark is not None else None
    except (TypeError, ValueError):
        current_mark = None

    if current_mark is not None and current_mark > 0:
        profit_pct = ((current_mark - option_entry) / option_entry) * 100.0
        for threshold, label in (
            (8.0, "8% Trail"), (7.0, "7% Trail"), (6.0, "6% Trail"),
            (5.0, "5% Trail"), (4.0, "4% Trail"), (3.0, "3% Stop"), (2.0, "2% Stop"),
        ):
            if profit_pct >= threshold:
                return label
        return "Stop"

    try:
        stop_price = float(stop_price or 0.0)
    except (TypeError, ValueError):
        stop_price = 0.0
    if stop_price > 0:
        stop_return_pct = ((stop_price - option_entry) / option_entry) * 100.0
        for threshold, label in (
            (6.9, "8% Trail"), (5.4, "7% Trail"), (3.9, "6% Trail"),
            (2.3, "5% Trail"), (0.8, "4% Trail"), (-1.0, "3% Stop"), (-3.0, "2% Stop"),
        ):
            if stop_return_pct >= threshold:
                return label
    return "Stop"


def classify_exit_reason(buy_event, sell_event):
    """Classify completed exits into the canonical stop and trail taxonomy."""
    order_type = str(sell_event.get("order_type") or "").upper()
    try:
        entry_price = float(buy_event.get("price") or 0)
        exit_price = float(sell_event.get("price") or 0)
        realized_pct = ((exit_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
    except (TypeError, ValueError):
        realized_pct = 0.0
    if realized_pct >= 6.0:
        return "6%+ TRAIL"
    if realized_pct >= 5.0:
        return "5% TRAIL"
    if realized_pct >= 4.0:
        return "4% TRAIL"
    if order_type in {"STOP", "STOP_LIMIT", "TRAILING_STOP", "TRAILING_STOP_LIMIT"} and realized_pct > 0.0:
        return "4% TRAIL"
    return "STOP"