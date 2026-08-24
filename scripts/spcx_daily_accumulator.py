#!/usr/bin/env python3
"""Governed one-share SPCX daily accumulation workflow.

The workflow is dry-run by default. Live submission requires both ``--execute``
and an explicit environment acknowledgement. It is intentionally isolated from
the SPY options engine so a failure here cannot alter option-trading behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd
from dotenv import load_dotenv

SYMBOL = "SPCX"
EXPECTED_CUSIP = "84615Q103"
QUANTITY = 1
CAP_MULTIPLIER = Decimal("1.000")
CANCEL_AFTER_SECONDS = 120
CANCEL_CONFIRM_SECONDS = 15
LIVE_ACK_VALUE = "SPCX_ONE_SHARE_DAILY_LIVE"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    # Direct script execution sets sys.path[0] to scripts/, not the repository
    # root. Keep shared operational helpers importable under the LaunchAgent.
    sys.path.insert(0, str(PROJECT_ROOT))
RUNTIME_ROOT = (
    Path.home()
    / "Library"
    / "Application Support"
    / "McLeod Alpha"
    / "runtime"
    / "spcx_daily_accumulator"
)
LEDGER_PATH = RUNTIME_ROOT / "ledger.jsonl"
LATEST_PATH = RUNTIME_ROOT / "latest.json"

ET = ZoneInfo("America/New_York")
XNYS = xcals.get_calendar("XNYS")

ACTIVE_OR_FILLED = {
    "ACCEPTED",
    "AWAITING_CONDITION",
    "AWAITING_PARENT_ORDER",
    "FILLED",
    "PARTIALLY_FILLED",
    "PENDING_ACTIVATION",
    "PENDING_REPLACEMENT",
    "QUEUED",
    "REPLACED",
    "WORKING",
}
TERMINAL_FILLED = {"FILLED"}
TERMINAL_NOT_FILLED = {"CANCELED", "EXPIRED", "REJECTED"}


@dataclass(frozen=True)
class QuoteSnapshot:
    symbol: str
    cusip: str
    description: str
    ask: Decimal
    bid: Decimal | None
    quote_time: str


@dataclass(frozen=True)
class OrderPlan:
    session_date: str
    symbol: str
    quantity: int
    ask: str
    limit_price: str
    cap_percent: str
    cancel_after_seconds: int
    account_suffix: str


def _now_et() -> datetime:
    return datetime.now(ET)


def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def is_trading_session(day: date) -> bool:
    return bool(XNYS.is_session(pd.Timestamp(day)))


def opening_window_is_valid(now: datetime) -> bool:
    local = now.astimezone(ET)
    minutes = local.hour * 60 + local.minute
    return 9 * 60 + 30 <= minutes <= 9 * 60 + 35


def capped_limit_price(ask: Decimal) -> Decimal:
    if ask <= 0:
        raise ValueError("ask must be positive")
    # Round down so the executable limit never exceeds the live ask.
    return (ask * CAP_MULTIPLIER).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def parse_quote(payload: dict[str, Any], now: datetime | None = None) -> QuoteSnapshot:
    blob = payload.get(SYMBOL) or {}
    quote = blob.get("quote") or {}
    reference = blob.get("reference") or {}
    security = blob.get("security") or {}

    symbol = str(blob.get("symbol") or reference.get("symbol") or SYMBOL).upper()
    cusip = str(reference.get("cusip") or security.get("cusip") or "").upper()
    description = str(
        reference.get("description")
        or security.get("description")
        or blob.get("description")
        or ""
    ).strip()
    ask = _decimal(quote.get("askPrice") or quote.get("ask"))
    bid = _decimal(quote.get("bidPrice") or quote.get("bid"))

    if symbol != SYMBOL:
        raise RuntimeError(f"identity guard failed: expected {SYMBOL}, received {symbol}")
    if cusip != EXPECTED_CUSIP:
        raise RuntimeError(
            f"identity guard failed: expected CUSIP {EXPECTED_CUSIP}, received {cusip or 'missing'}"
        )
    if "SPACE" not in description.upper():
        raise RuntimeError(
            f"identity guard failed: unexpected description {description or 'missing'}"
        )
    if ask is None or ask <= 0:
        raise RuntimeError("quote guard failed: positive live ask unavailable")

    stamp = (now or _now_et()).astimezone(ET)
    return QuoteSnapshot(
        symbol=symbol,
        cusip=cusip,
        description=description,
        ask=ask,
        bid=bid,
        quote_time=stamp.isoformat(),
    )


def _order_date(order: dict[str, Any]) -> date | None:
    raw = order.get("enteredTime") or order.get("closeTime")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(ET).date()
    except Exception:
        return None


def _is_spcx_buy(order: dict[str, Any]) -> bool:
    for strategy in order.get("orderLegCollection") or []:
        instrument = strategy.get("instrument") or {}
        instruction = str(strategy.get("instruction") or "").upper()
        symbol = str(instrument.get("symbol") or "").upper()
        if symbol == SYMBOL and instruction in {"BUY", "BUY_TO_OPEN"}:
            return True
    return False


def duplicate_order_exists(orders: list[dict[str, Any]], session_day: date) -> bool:
    for order in orders:
        status = str(order.get("status") or "").upper()
        if status not in ACTIVE_OR_FILLED:
            continue
        if _order_date(order) != session_day:
            continue
        if _is_spcx_buy(order):
            return True
    return False


def _ledger_has_submission_started(
    session_day: date, ledger_path: Path | None = None
) -> bool:
    ledger_path = ledger_path or LEDGER_PATH
    if not ledger_path.exists():
        return False
    unresolved_submission = False
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        if event.get("session_date") != session_day.isoformat():
            continue
        event_type = str(event.get("event") or "")
        status = str(event.get("status") or "").upper()
        if event_type == "filled":
            return True
        if event_type in {"submission_started", "submitted"}:
            unresolved_submission = True
        if event_type == "terminal" and status in TERMINAL_NOT_FILLED:
            # A confirmed non-fill is safe to retry because the broker-level
            # duplicate check runs before this ledger guard on every attempt.
            unresolved_submission = False
    return unresolved_submission


def _record(event: dict[str, Any], ledger_path: Path | None = None) -> None:
    def json_default(value: Any) -> str:
        if isinstance(value, Decimal):
            return str(value)
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    ledger_path = ledger_path or LEDGER_PATH
    payload = dict(event)
    payload.setdefault("recorded_at", _now_et().isoformat())
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=json_default) + "\n")
    LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=json_default),
        encoding="utf-8",
    )


def _extract_available_cash(account_payload: dict[str, Any]) -> Decimal:
    account = account_payload.get("securitiesAccount") or account_payload
    balances = account.get("currentBalances") or {}
    for key in (
        "cashAvailableForTrading",
        "availableFundsNonMarginableTrade",
        "buyingPowerNonMarginableTrade",
    ):
        value = _decimal(balances.get(key))
        if value is not None and value >= 0:
            return value
    raise RuntimeError("cash guard failed: non-margin buying power unavailable")


def _order_id_from_response(response: Any) -> str:
    location = str((getattr(response, "headers", {}) or {}).get("Location") or "")
    order_id = location.rstrip("/").split("/")[-1] if location else ""
    if not order_id or order_id == "orders":
        raise RuntimeError("submission outcome ambiguous: Schwab returned no order ID")
    return order_id


def _build_limit_order(limit_price: Decimal) -> Any:
    from schwab.orders.common import (
        Duration,
        EquityInstruction,
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
        .set_order_type(OrderType.LIMIT)
        .set_price(str(limit_price))
        .add_equity_leg(EquityInstruction.BUY, SYMBOL, QUANTITY)
    )


def _create_client() -> Any:
    from schwab.auth import client_from_token_file

    token_path = Path(os.getenv("SCHWAB_TOKEN_PATH", str(PROJECT_ROOT / "token.json"))).expanduser()
    if not token_path.exists():
        raise FileNotFoundError("Schwab token file is missing")
    return client_from_token_file(
        token_path=str(token_path),
        api_key=os.getenv("SCHWAB_APP_KEY"),
        app_secret=os.getenv("SCHWAB_APP_SECRET"),
        enforce_enums=False,
    )


def _fetch_quote(client: Any) -> QuoteSnapshot:
    response = client.get_quote(SYMBOL)
    response.raise_for_status()
    return parse_quote(response.json() or {})


def _get_account_hash() -> str:
    account_hash = os.getenv("SCHWAB_ACCOUNT_HASH", "").strip()
    account_number = os.getenv("SCHWAB_ACCOUNT_NUMBER", "").strip()
    if not account_hash or not account_number:
        raise RuntimeError("account guard failed: configured Schwab account number/hash required")
    return account_hash


def _execution_price(order: dict[str, Any]) -> str | None:
    prices: list[tuple[Decimal, Decimal]] = []
    for activity in order.get("orderActivityCollection") or []:
        for leg in activity.get("executionLegs") or []:
            price = _decimal(leg.get("price"))
            quantity = _decimal(leg.get("quantity"))
            if price is not None and quantity is not None and quantity > 0:
                prices.append((price, quantity))
    if not prices:
        return None
    total_quantity = sum((quantity for _, quantity in prices), Decimal("0"))
    total_value = sum((price * quantity for price, quantity in prices), Decimal("0"))
    if total_quantity <= 0:
        return None
    return str((total_value / total_quantity).quantize(Decimal("0.0001")))


def _response_status(response: Any) -> int | None:
    """Return an HTTP status without requiring a concrete httpx response type."""
    value = getattr(response, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _order_from_account_list(
    client: Any, account_hash: str, order_id: str
) -> dict[str, Any] | None:
    """Recover an order when Schwab's single-order endpoint returns a 400.

    Schwab can reject ``GET /orders/{id}`` for an order that is still visible in
    the account collection (notably immediately after submission).  The account
    collection is the authoritative fallback and avoids treating a transient
    polling failure as a failed or duplicate purchase.
    """
    response = client.get_orders_for_account(account_hash)
    response.raise_for_status()
    for order in response.json() or []:
        candidate_id = str(order.get("orderId") or order.get("order_id") or "")
        if candidate_id == str(order_id):
            return order
    return None


def _wait_for_terminal_state(
    client: Any, account_hash: str, order_id: str
) -> tuple[str, dict[str, Any]]:
    deadline = time.monotonic() + CANCEL_AFTER_SECONDS
    last_order: dict[str, Any] = {}
    poll_errors: list[str] = []
    while time.monotonic() < deadline:
        response = None
        try:
            response = client.get_order(order_id, account_hash)
            response.raise_for_status()
            last_order = response.json() or {}
        except Exception as exc:
            # A 400 from the single-order endpoint is recoverable through the
            # account-level order collection. Other failures remain fatal.
            status_code = _response_status(locals().get("response"))
            if status_code != 400:
                raise
            poll_errors.append(f"single_order_400:{exc}")
            try:
                recovered = _order_from_account_list(client, account_hash, order_id)
            except Exception as fallback_exc:
                poll_errors.append(f"account_order_fallback_error:{fallback_exc}")
                recovered = None
            if recovered is not None:
                last_order = recovered
            else:
                last_order = {
                    "orderId": str(order_id),
                    "status": "STATUS_UNCERTAIN",
                    "status_poll_errors": poll_errors[-3:],
                }
        status = str(last_order.get("status") or "").upper()
        if status in TERMINAL_FILLED:
            return status, last_order
        if status in TERMINAL_NOT_FILLED:
            return status, last_order
        time.sleep(5)

    # Before cancelling, recover the latest account-level status. If Schwab
    # cannot identify the order, preserve uncertainty rather than issuing a
    # blind cancellation against an order that may already have filled.
    try:
        recovered = _order_from_account_list(client, account_hash, order_id)
    except Exception as exc:
        poll_errors.append(f"account_order_final_fallback_error:{exc}")
        recovered = None
    if recovered is not None:
        last_order = recovered
        status = str(last_order.get("status") or "").upper()
        if status in TERMINAL_FILLED or status in TERMINAL_NOT_FILLED:
            return status, last_order
    if not last_order or str(last_order.get("status") or "").upper() == "STATUS_UNCERTAIN":
        return "STATUS_UNCERTAIN", {
            "orderId": str(order_id),
            "status": "STATUS_UNCERTAIN",
            "status_poll_errors": poll_errors[-5:],
        }

    response = client.cancel_order(order_id, account_hash)
    response.raise_for_status()
    cancel_deadline = time.monotonic() + CANCEL_CONFIRM_SECONDS
    while time.monotonic() < cancel_deadline:
        try:
            recovered = _order_from_account_list(client, account_hash, order_id)
        except Exception as exc:
            poll_errors.append(f"cancel_confirmation_error:{exc}")
            recovered = None
        if recovered is not None:
            last_order = recovered
            status = str(last_order.get("status") or "").upper()
            if status in TERMINAL_FILLED or status in TERMINAL_NOT_FILLED:
                return status, last_order
        time.sleep(2)
    return "STATUS_UNCERTAIN", {
        "orderId": str(order_id),
        "status": "STATUS_UNCERTAIN",
        "cancel_requested": True,
        "status_poll_errors": poll_errors[-5:],
    }


def _set_failure_alert(reason: str, message: str) -> None:
    from ops.runtime_alerts import set_runtime_alert

    set_runtime_alert(reason, message, severity="critical")
    print(f"SPCX_BUY: FAIL | {reason} | {message}")


def _clear_failure_alerts() -> None:
    from ops.runtime_alerts import clear_runtime_alert

    clear_runtime_alert("schwab_reauthentication_required")
    clear_runtime_alert("spcx_daily_accumulator_nonfill")
    clear_runtime_alert("spcx_daily_accumulator_unresolved")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Governed daily one-share SPCX accumulator.")
    parser.add_argument("--execute", action="store_true", help="Submit the live Schwab order.")
    parser.add_argument("--force", action="store_true", help="Bypass date/time gates for dry-run tests.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _load_env()
    args = _parse_args(argv)
    now = _now_et()
    session_day = now.date()

    if args.execute and args.force:
        raise RuntimeError("--force is prohibited with --execute")
    if not args.force and not is_trading_session(session_day):
        _record({"event": "skipped", "reason": "not_trading_session", "session_date": session_day.isoformat()})
        return 0
    if not args.force and not opening_window_is_valid(now):
        _record({"event": "skipped", "reason": "outside_opening_window", "session_date": session_day.isoformat()})
        return 0

    try:
        client = _create_client()
    except Exception as exc:
        from ops.runtime_alerts import set_runtime_alert

        _record(
            {
                "event": "blocked",
                "reason": "schwab_reauthentication_required",
                "session_date": session_day.isoformat(),
                "error_type": type(exc).__name__,
            }
        )
        set_runtime_alert(
            "schwab_reauthentication_required",
            "Schwab API authentication expired; SPCX accumulation was blocked",
            severity="critical",
        )
        print(
            "SPCX_AUTH: FAIL | reauthentication required | "
            f"{type(exc).__name__}"
        )
        return 1
    account_hash = _get_account_hash()
    account_suffix = os.getenv("SCHWAB_ACCOUNT_NUMBER", "")[-4:]

    orders_response = client.get_orders_for_account(account_hash)
    orders_response.raise_for_status()
    broker_orders = orders_response.json() or []
    if duplicate_order_exists(broker_orders, session_day):
        _record({"event": "skipped", "reason": "broker_duplicate_guard", "session_date": session_day.isoformat()})
        if any(
            str(order.get("status") or "").upper() == "FILLED"
            and _order_date(order) == session_day
            and _is_spcx_buy(order)
            for order in broker_orders
        ):
            _clear_failure_alerts()
        return 0
    if _ledger_has_submission_started(session_day):
        _record({"event": "blocked", "reason": "unresolved_prior_submission", "session_date": session_day.isoformat()})
        _set_failure_alert(
            "spcx_daily_accumulator_unresolved",
            "Prior SPCX submission is unresolved; recovery was blocked to prevent a duplicate buy",
        )
        return 1

    quote = _fetch_quote(client)
    limit_price = capped_limit_price(quote.ask)

    account_response = client.get_account(account_hash)
    account_response.raise_for_status()
    cash = _extract_available_cash(account_response.json() or {})
    if cash < limit_price:
        _record(
            {
                "event": "skipped",
                "reason": "insufficient_non_margin_cash",
                "session_date": session_day.isoformat(),
                "required": str(limit_price),
                "available": str(cash),
            }
        )
        _set_failure_alert(
            "spcx_daily_accumulator_nonfill",
            "SPCX accumulation was blocked by insufficient non-margin cash",
        )
        return 1

    plan = OrderPlan(
        session_date=session_day.isoformat(),
        symbol=SYMBOL,
        quantity=QUANTITY,
        ask=str(quote.ask),
        limit_price=str(limit_price),
        cap_percent="0.00",
        cancel_after_seconds=CANCEL_AFTER_SECONDS,
        account_suffix=account_suffix,
    )

    if not args.execute:
        _record({"event": "dry_run", "plan": asdict(plan), "quote": asdict(quote)})
        return 0

    if os.getenv("SPCX_AUTOMATION_LIVE_ACK", "").strip() != LIVE_ACK_VALUE:
        _record(
            {
                "event": "blocked",
                "reason": "live_execution_ack_missing",
                "session_date": session_day.isoformat(),
            }
        )
        _set_failure_alert(
            "spcx_daily_accumulator_nonfill",
            "SPCX live execution acknowledgement is missing",
        )
        return 1

    _record({"event": "submission_started", "session_date": session_day.isoformat(), "plan": asdict(plan)})
    try:
        response = client.place_order(account_hash, _build_limit_order(limit_price))
        response.raise_for_status()
        order_id = _order_id_from_response(response)
    except Exception as exc:
        _record(
            {
                "event": "blocked",
                "reason": "submission_outcome_uncertain",
                "session_date": session_day.isoformat(),
                "error_type": type(exc).__name__,
                "plan": asdict(plan),
            }
        )
        _set_failure_alert(
            "spcx_daily_accumulator_unresolved",
            "SPCX submission outcome is uncertain; automatic recovery was blocked to prevent a duplicate buy",
        )
        return 1
    _record(
        {
            "event": "submitted",
            "session_date": session_day.isoformat(),
            "order_id": order_id,
            "plan": asdict(plan),
        }
    )

    try:
        status, terminal_order = _wait_for_terminal_state(client, account_hash, order_id)
    except Exception as exc:
        _record(
            {
                "event": "terminal",
                "session_date": session_day.isoformat(),
                "order_id": order_id,
                "status": "STATUS_UNCERTAIN",
                "error_type": type(exc).__name__,
                "plan": asdict(plan),
            }
        )
        _set_failure_alert(
            "spcx_daily_accumulator_unresolved",
            f"SPCX order {order_id} status is uncertain; automatic recovery was blocked to prevent a duplicate buy",
        )
        return 1
    _record(
        {
            "event": "filled" if status == "FILLED" else "terminal",
            "session_date": session_day.isoformat(),
            "order_id": order_id,
            "status": status,
            "execution_price": _execution_price(terminal_order),
            "plan": asdict(plan),
        }
    )
    if status == "FILLED":
        _clear_failure_alerts()
        return 0

    _set_failure_alert(
        "spcx_daily_accumulator_nonfill" if status in TERMINAL_NOT_FILLED else "spcx_daily_accumulator_unresolved",
        f"SPCX order {order_id} did not fill; terminal status={status}",
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
