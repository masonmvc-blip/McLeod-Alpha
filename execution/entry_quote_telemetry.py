"""Attach observed entry quote and fill facts to immutable trade diagnostics."""

from __future__ import annotations

import json
from typing import Any


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def attach_entry_quote_telemetry(
    feature_payload: str | dict[str, Any] | None,
    *,
    quote_snapshot: dict[str, Any],
    submitted_limit_price: Any,
    broker_fill_price: Any,
    filled_via: str | None,
) -> str:
    """Return an enriched payload; never returns execution instructions."""
    if isinstance(feature_payload, dict):
        payload = dict(feature_payload)
    else:
        try:
            parsed = json.loads(str(feature_payload or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = {}
        payload = parsed if isinstance(parsed, dict) else {}
    limit_price = _number(submitted_limit_price)
    fill_price = _number(broker_fill_price)
    quote = {
        "bid": _number(quote_snapshot.get("bid")),
        "ask": _number(quote_snapshot.get("ask")),
        "mark": _number(quote_snapshot.get("mark")),
        "last": _number(quote_snapshot.get("last")),
        "quote_age_seconds": _number(quote_snapshot.get("quote_age_seconds")),
        "spread_pct": _number(
            quote_snapshot.get("quote_spread_pct")
            if quote_snapshot.get("quote_spread_pct") is not None
            else quote_snapshot.get("spread_pct")
        ),
        "quote_as_of": quote_snapshot.get("quote_as_of"),
        "quote_source": quote_snapshot.get("quote_source"),
        "submitted_limit_price": limit_price,
        "broker_fill_price": fill_price,
        "filled_via": filled_via,
        "slippage_vs_limit_dollars": (
            round(fill_price - limit_price, 6)
            if fill_price is not None and limit_price is not None
            else None
        ),
        "provenance": "captured_live_pre_submit_quote_and_broker_fill",
    }
    payload["entry_option_quote_snapshot"] = quote
    suite = payload.get("day_trade_spy_shadow_suite")
    if isinstance(suite, dict):
        tests = suite.get("tests")
        structural = tests.get("structural_room_execution") if isinstance(tests, dict) else None
        inputs = structural.get("inputs") if isinstance(structural, dict) else None
        if isinstance(inputs, dict):
            inputs["entry_quote_snapshot"] = quote
    return json.dumps(payload, default=str)
