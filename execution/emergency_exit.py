"""Broker-direct emergency flattening for long SPY option positions."""

from __future__ import annotations

import time
from typing import Any


ACTIVE_ORDER_STATUSES = {
    "PENDING_ACTIVATION", "ACCEPTED", "QUEUED", "WORKING",
    "PENDING_REPLACEMENT", "PARTIALLY_FILLED", "AWAITING_PARENT_ORDER",
    "AWAITING_CONDITION",
}


def _json(response: Any) -> Any:
    response.raise_for_status()
    return response.json() or {}


def _snapshot(client: Any, account_hash: str) -> tuple[list[dict], list[dict]]:
    account = _json(
        client.get_account(
            account_hash,
            fields=[client.Account.Fields.POSITIONS],
        )
    )
    positions = (
        account.get("securitiesAccount", {}).get("positions", []) or []
    )
    orders = _json(client.get_orders_for_account(account_hash))
    return positions, orders if isinstance(orders, list) else []


def _spy_long_options(positions: list[dict]) -> dict[str, int]:
    result: dict[str, int] = {}
    for position in positions:
        instrument = position.get("instrument", {}) or {}
        symbol = str(instrument.get("symbol") or "")
        if (
            str(instrument.get("assetType") or "").upper() != "OPTION"
            or not symbol.startswith("SPY")
        ):
            continue
        quantity = int(float(position.get("longQuantity") or 0))
        if quantity > 0:
            result[symbol] = result.get(symbol, 0) + quantity
    return result


def _active_spy_closing_orders(orders: list[dict]) -> list[str]:
    ids: list[str] = []
    for order in orders:
        if str(order.get("status") or "").upper() not in ACTIVE_ORDER_STATUSES:
            continue
        if not any(
            str(leg.get("instruction") or "").upper() == "SELL_TO_CLOSE"
            and str((leg.get("instrument") or {}).get("assetType") or "").upper()
            == "OPTION"
            and str((leg.get("instrument") or {}).get("symbol") or "").startswith(
                "SPY"
            )
            for leg in order.get("orderLegCollection", []) or []
        ):
            continue
        order_id = str(order.get("orderId") or "")
        if order_id and order_id not in ids:
            ids.append(order_id)
    return ids


def _market_close_order(symbol: str, quantity: int):
    from schwab.orders.common import (
        Duration,
        OptionInstruction,
        OrderStrategyType,
        OrderType,
        Session,
    )
    from schwab.orders.generic import OrderBuilder

    return (
        OrderBuilder()
        .set_session(Session.NORMAL)
        .set_duration(Duration.DAY)
        .set_order_strategy_type(OrderStrategyType.SINGLE)
        .set_order_type(OrderType.MARKET)
        .add_option_leg(OptionInstruction.SELL_TO_CLOSE, symbol, quantity)
    )


def flatten_all_spy_options(
    client: Any,
    account_hash: str,
    *,
    timeout_seconds: float = 10.0,
    poll_seconds: float = 0.25,
) -> dict[str, Any]:
    """Cancel SPY closing reservations, market-close every long, and verify flat."""
    started = time.monotonic()
    positions, orders = _snapshot(client, account_hash)
    initial = _spy_long_options(positions)
    if not initial:
        return {
            "status": "flat",
            "initial_positions": {},
            "submitted_orders": [],
            "elapsed_seconds": round(time.monotonic() - started, 4),
        }

    canceled: list[str] = []
    for order_id in _active_spy_closing_orders(orders):
        response = client.cancel_order(order_id, account_hash)
        response.raise_for_status()
        canceled.append(order_id)

    # Confirm reservations are actually released before sending a full close.
    # This prevents both broker rejection and an accidental over-close.
    cancel_deadline = min(started + 3.0, started + timeout_seconds)
    while True:
        positions, orders = _snapshot(client, account_hash)
        active_reservations = _active_spy_closing_orders(orders)
        if not active_reservations:
            break
        if time.monotonic() >= cancel_deadline:
            return {
                "status": "unconfirmed",
                "initial_positions": initial,
                "canceled_order_ids": canceled,
                "active_reservation_ids": active_reservations,
                "submitted_orders": [],
                "remaining_positions": _spy_long_options(positions),
                "elapsed_seconds": round(time.monotonic() - started, 4),
            }
        time.sleep(min(poll_seconds, 0.1))

    # Re-read broker quantity after reservations are released. This prevents
    # stale local size and partial fills from producing an over-close.
    remaining = _spy_long_options(positions)
    submitted: list[dict[str, Any]] = []
    for symbol, quantity in remaining.items():
        response = client.place_order(
            account_hash,
            _market_close_order(symbol, quantity),
        )
        response.raise_for_status()
        location = str(response.headers.get("Location") or "")
        submitted.append({
            "symbol": symbol,
            "quantity": quantity,
            "order_id": location.rstrip("/").split("/")[-1] if location else None,
        })

    deadline = started + timeout_seconds
    last_remaining = remaining
    while time.monotonic() < deadline:
        positions, _ = _snapshot(client, account_hash)
        last_remaining = _spy_long_options(positions)
        if not last_remaining:
            return {
                "status": "flat",
                "initial_positions": initial,
                "canceled_order_ids": canceled,
                "submitted_orders": submitted,
                "remaining_positions": {},
                "elapsed_seconds": round(time.monotonic() - started, 4),
            }
        time.sleep(poll_seconds)

    return {
        "status": "unconfirmed",
        "initial_positions": initial,
        "canceled_order_ids": canceled,
        "submitted_orders": submitted,
        "remaining_positions": last_remaining,
        "elapsed_seconds": round(time.monotonic() - started, 4),
    }
