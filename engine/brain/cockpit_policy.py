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
            (4.0, "4% Trail"), (3.0, "3% Stop"), (2.0, "2% Stop"), (1.0, "1% Stop"),
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
            (2.5, "4% Trail"), (1.4, "3% Stop"), (-0.1, "2% Stop"), (-2.1, "1% Stop"),
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
    if realized_pct >= 4.0:
        return "4% TRAIL"
    if realized_pct >= 3.0:
        return "3% Stop"
    if realized_pct >= 2.0:
        return "2% Stop"
    if realized_pct >= 1.0:
        return "1% Stop"
    if order_type in {"STOP", "STOP_LIMIT", "TRAILING_STOP", "TRAILING_STOP_LIMIT"} and realized_pct > 0.0:
        return "4% TRAIL"
    return "STOP"


def indicator_no_entry_reasons(audit_event):
    """Explain why a fully-qualified side was declined on a closed candle."""
    if not audit_event:
        return {"CALL": None, "PUT": None}
    reason = str(audit_event.get("entry_decision_reason") or "").strip().replace("_", " ") or None
    regime = str(audit_event.get("regime") or "").replace("_", " ").title()
    return {
        "CALL": "Trend is Neutral or Bear" if audit_event.get("call_score") == 5 and regime != "Bull Trend" else reason,
        "PUT": f"Regime is {regime}; PUT requires BEAR TREND" if audit_event.get("put_score") == 5 and regime != "Bear Trend" else reason,
    }