"""Append-only executable option quote telemetry for autonomous trade research."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from execution.exit_quality import executable_option_price


EASTERN_TZ = ZoneInfo("America/New_York")
OPTION_TELEMETRY_DIR = Path(os.getenv("OPTION_TELEMETRY_DIR", "data/reports/option_quote_telemetry"))


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _percent(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(numerator / denominator * 100.0, 4)


def build_option_management_cycle(
    position: Any,
    *,
    spy_price: Any,
    bid: Any = None,
    ask: Any = None,
    mark: Any = None,
    last: Any = None,
    quote_metadata: dict[str, Any] | None = None,
    action: Any = None,
    reason: Any = None,
    event_type: str = "option_management_cycle",
    broker_exit_order_id: Any = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a research record from facts already observed by the live manager."""
    timestamp = observed_at or datetime.now(EASTERN_TZ)
    bid_value, ask_value, mark_value, last_value = (_positive_number(value) for value in (bid, ask, mark, last))
    executable_price, executable_source = executable_option_price(bid=bid_value, last=last_value, mark=mark_value)
    entry = _positive_number(getattr(position, "option_entry", None))
    high = _positive_number(getattr(position, "option_high_since_entry", None))
    low = _positive_number(getattr(position, "option_low_since_entry", None))
    quantity = max(0, int(getattr(position, "quantity", 0) or 0))
    spread_dollars = round(ask_value - bid_value, 6) if bid_value and ask_value and ask_value >= bid_value else None
    metadata = quote_metadata or {}
    try:
        feature_payload = json.loads(str(getattr(position, "feature_payload", "") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        feature_payload = {}
    return {
        "schema_version": "option-management-cycle.v1",
        "recorded_at": timestamp.isoformat(),
        "event_type": event_type,
        "trade_key": f"{getattr(position, 'option_symbol', '')}:{getattr(position, 'opened', '')}",
        "option_symbol": getattr(position, "option_symbol", ""),
        "direction": getattr(position, "direction", ""),
        "quantity": quantity,
        "broker_entry_order_id": str(getattr(position, "schwab_order_id", "") or "") or None,
        "broker_entry_fill_price": _positive_number(getattr(position, "schwab_fill_price", None)) or entry,
        "broker_entry_fill_timestamp": getattr(position, "schwab_fill_timestamp", "") or None,
        "broker_exit_order_id": str(broker_exit_order_id or "") or None,
        "option_entry": entry,
        "spy_price": _positive_number(spy_price),
        "bid": bid_value,
        "ask": ask_value,
        "mark": mark_value,
        "last": last_value,
        "executable_exit_price": executable_price,
        "executable_exit_source": executable_source,
        "spread_dollars": spread_dollars,
        "spread_pct": _percent(spread_dollars, mark_value),
        "estimated_exit_spread_cost_dollars": round((spread_dollars or 0.0) * quantity * 100.0, 4),
        "quote_age_seconds": metadata.get("quote_age_seconds"),
        "quote_source": metadata.get("quote_source"),
        "option_stop": _positive_number(getattr(position, "option_stop", None)),
        "option_high_since_entry": high,
        "option_low_since_entry": low,
        "mfe_pct_live": _percent((high - entry) if high and entry else None, entry),
        "mae_pct_live": _percent((low - entry) if low and entry else None, entry),
        "decision_action": str(action) if action is not None else None,
        "decision_reason": str(reason) if reason is not None else None,
        "accepted_breakout_observer_id": feature_payload.get("accepted_breakout_observer_id"),
        "accepted_breakout_admit": feature_payload.get("accepted_breakout_admit"),
        "accepted_breakout_reason": feature_payload.get("accepted_breakout_reason"),
        "structural_room": feature_payload.get("support_resistance"),
        "broker_fees_dollars": feature_payload.get("broker_fees_dollars"),
    }


def record_option_management_cycle(position: Any, **kwargs: Any) -> None:
    """Best-effort immutable write; telemetry must never affect execution."""
    try:
        payload = build_option_management_cycle(position, **kwargs)
        timestamp = datetime.now(EASTERN_TZ)
        path = OPTION_TELEMETRY_DIR / f"option_management_cycles_{timestamp.date().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    except Exception:
        pass