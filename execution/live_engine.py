"""
Live Schwab order execution engine with ACTUAL order submission.

This module provides the sole live trading execution pipeline for placing real
orders on Schwab accounts.

KEY DIFFERENCES FROM STUB:
- Actually calls client.place_order() with real Schwab orders
- Waits for fill confirmation before creating position
- Stores order ID, fill price, fill timestamp
- Implements reconciliation with Schwab at startup
- Provides safe cleanup only after Schwab confirmation
"""

from execution.position_store import save_position, load_position, clear_position
from execution.sms_alerts import send_trade_entry_alert, send_trade_exit_alert, send_emergency_alert
from execution.contract_limits import MAX_OPEN_CONTRACTS
from execution.diagnostic_snapshots import extract_entry_diagnostic_snapshot
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as dt_time, timezone
from zoneinfo import ZoneInfo
from engine.brain import Brain, TradeAction, can_open_trade, record_trade, record_stop
from engine.brain.engine import MAX_TRADE_HOLD_MINUTES
from engine.memory import get_memory
from execution.trade_logger import log_trade, log_bot_order, log_trade_diagnostic_event
import os
import time
import json
import sqlite3
from pathlib import Path

# Global Schwab client and account configuration
# Set by phase3_monitor.py after client creation
_schwab_client = None
_schwab_account_number = None
_schwab_account_hash = None
_last_broker_sync_epoch = 0.0
BROKER_SYNC_MIN_INTERVAL_SECONDS = float(os.getenv("BROKER_SYNC_MIN_INTERVAL_SECONDS", "2.0"))
PROTECTIVE_STOP_CHECK_MIN_INTERVAL_SECONDS = float(os.getenv("PROTECTIVE_STOP_CHECK_MIN_INTERVAL_SECONDS", "1.0"))
_last_protective_stop_check_epoch = 0.0
_last_protective_stop_check_ok = True
BROKER_RECONCILE_MAX_ATTEMPTS = max(1, int(os.getenv("BROKER_RECONCILE_MAX_ATTEMPTS", "3")))
BROKER_RECONCILE_RETRY_DELAY_SECONDS = max(1.0, float(os.getenv("BROKER_RECONCILE_RETRY_DELAY_SECONDS", "6")))
OPTION_QUOTE_MAX_STALE_SECONDS_OPEN = max(1.0, float(os.getenv("OPTION_QUOTE_MAX_STALE_SECONDS_OPEN", "8")))
OPTION_QUOTE_MAX_SPREAD_PCT_OPEN = max(0.0, float(os.getenv("OPTION_QUOTE_MAX_SPREAD_PCT_OPEN", "15")))


def _perf_ms_now():
    return time.perf_counter() * 1000.0


def _elapsed_ms(start_ms):
    return round(max(0.0, _perf_ms_now() - float(start_ms or 0.0)), 2)


def set_schwab_client(client, account_number, account_hash):
    """
    Configure Schwab client for live order execution.
    Called by phase3_monitor.py during initialization.
    
    Args:
        client: Schwab easy_client instance
        account_number: Schwab account number (e.g., "33310903")
        account_hash: Schwab account hash for order placement
    """
    global _schwab_client, _schwab_account_number, _schwab_account_hash, _submission_rejected, _rejection_reason
    global _entry_pending, _pending_order_id, _max_quantity_exceeded, _excess_quantity_details
    global _safe_mode, _safe_mode_reason, _protective_stop_failed, _protective_stop_failure_reason
    global _last_broker_sync_epoch, _last_protective_stop_check_epoch, _last_protective_stop_check_ok
    global LAST_OPEN_TRADE_METRICS
    
    _schwab_client = client
    _schwab_account_number = account_number
    _schwab_account_hash = account_hash
    
    # Reset locks on reconfiguration (for testing or restart)
    _submission_rejected = False
    _rejection_reason = None
    _entry_pending = False
    _pending_order_id = None
    _max_quantity_exceeded = False
    _excess_quantity_details = None
    _safe_mode = False
    _safe_mode_reason = None
    _protective_stop_failed = False
    _protective_stop_failure_reason = None
    _last_broker_sync_epoch = 0.0
    _last_protective_stop_check_epoch = 0.0
    _last_protective_stop_check_ok = True
    LAST_OPEN_TRADE_METRICS = {
        "attempted": False,
        "opened": False,
        "block_reason": None,
        "precheck_ms": None,
        "quote_compute_ms": None,
        "submit_order_ms": None,
        "wait_fill_ms": None,
        "market_fallback_submit_ms": None,
        "market_fallback_wait_ms": None,
        "protective_stop_ms": None,
        "persist_ms": None,
        "total_open_trade_ms": None,
        "filled_via": None,
    }


def safe_log_trade(**kwargs):
    """Pass only arguments supported by the current trade logger."""
    import inspect

    supported = inspect.signature(log_trade).parameters

    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in supported.values()
    ):
        return log_trade(**kwargs)

    filtered = {
        key: value
        for key, value in kwargs.items()
        if key in supported
    }

    return log_trade(**filtered)


def _audit_bot_order(order_id, intent):
    """Best-effort audit of bot-submitted broker order IDs."""
    try:
        log_bot_order(order_id, intent)
    except Exception as exc:
        print(f"WARNING: Could not audit bot order {order_id} ({intent}): {exc}")


def _coerce_epoch_seconds(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if numeric <= 0:
        return None

    if numeric > 1_000_000_000_000:
        return numeric / 1000.0

    if numeric > 1_000_000_000:
        return numeric

    return None


def _extract_quote_epoch_seconds(*payloads):
    candidate_keys = (
        "quoteTimeInLong",
        "tradeTimeInLong",
        "regularMarketTradeTimeInLong",
        "lastTradeTimeInLong",
        "timestamp",
        "lastTradeTimestamp",
    )

    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in candidate_keys:
            epoch = _coerce_epoch_seconds(payload.get(key))
            if epoch is not None:
                return epoch
    return None


def sanitize_for_logging(text):
    """
    Sanitize response data by masking sensitive credentials and tokens.
    Keep all other information intact for debugging.
    
    Args:
        text: Raw response text
    
    Returns:
        Sanitized text with tokens masked
    """
    import re
    
    if not text:
        return text
    
    # Mask patterns that might contain tokens/credentials
    # Mask Authorization headers
    text = re.sub(
        r'(["\']?Authorization["\']?\s*[=:]\s*["\']?)Bearer\s+[^\s"\']+',
        r'\1Bearer [MASKED]',
        text,
        flags=re.IGNORECASE
    )
    
    # Mask access_token values
    text = re.sub(
        r'(["\']?access_token["\']?\s*[=:]\s*["\']?)[^\s"\']*',
        r'\1[MASKED]',
        text,
        flags=re.IGNORECASE
    )
    
    # Mask refresh_token values
    text = re.sub(
        r'(["\']?refresh_token["\']?\s*[=:]\s*["\']?)[^\s"\']*',
        r'\1[MASKED]',
        text,
        flags=re.IGNORECASE
    )
    
    # Mask API keys/secrets (partial masking - show first/last 3 chars)
    text = re.sub(
        r'(["\']?api[_-]?secret["\']?\s*[=:]\s*["\']?)([a-zA-Z0-9]{6})([a-zA-Z0-9]*)',
        lambda m: m.group(1) + m.group(2) + '[MASKED]' if len(m.group(3)) > 3 else m.group(0),
        text,
        flags=re.IGNORECASE
    )
    
    return text


def get_schwab_positions():
    """
    Query Schwab for current positions and open orders.
    
    Returns:
        (positions, orders, status_code, response_text) tuple
        On success: (positions_list, orders_list, 200, None)
        On error: (None, None, status_code, response_text)
    """
    if not _schwab_client or not _schwab_account_hash:
        return None, None, None, "Client or account hash not configured"
    
    try:
        # Get positions using get_account with POSITIONS field enum
        resp_account = _schwab_client.get_account(
            _schwab_account_hash,
            fields=[_schwab_client.Account.Fields.POSITIONS]
        )
        resp_account.raise_for_status()
        account_data = resp_account.json()
        
        positions = account_data.get("securitiesAccount", {}).get("positions", [])
        
        # Prefer dedicated orders endpoint, but gracefully fall back to account payload.
        orders = []
        try:
            resp_orders = _schwab_client.get_orders_for_account(_schwab_account_hash)
            resp_orders.raise_for_status()
            orders_data = resp_orders.json()
            if isinstance(orders_data, list):
                orders = orders_data
            else:
                # Some mocked clients return non-list placeholders here.
                orders = account_data.get("securitiesAccount", {}).get("orderStrategies", []) or []
        except Exception:
            # Some test/mocked clients only expose orderStrategies on get_account.
            orders = account_data.get("securitiesAccount", {}).get("orderStrategies", []) or []
        
        return positions, orders, 200, None
    except Exception as e:
        # Return error details for SAFE MODE
        status_code = getattr(e, 'status_code', None)
        if hasattr(e, 'response'):
            try:
                response_text = e.response.text if hasattr(e.response, 'text') else str(e)
            except:
                response_text = str(e)
        else:
            response_text = str(e)
        
        return None, None, status_code, response_text


def _is_retryable_broker_error(status_code, error_text):
    """Return True when a startup reconciliation failure is likely transient."""
    try:
        code = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        code = None

    if code is not None and 500 <= code < 600:
        return True

    text = str(error_text or "").lower()
    transient_markers = (
        "timed out",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "service unavailable",
        "unexpected error",
        "internal server error",
    )
    return any(marker in text for marker in transient_markers)


def check_spy_option_exposure():
    """
    Check Schwab for existing SPY option positions or active pending orders.
    
    Only blocks trading if:
    1. There is an open SPY option position (longQuantity > 0), OR
    2. There is an ACTIVE SPY option order (status that can still result in a fill)
    
    Terminal statuses (FILLED, CANCELED, REPLACED, EXPIRED, REJECTED) never block.
    
    Returns:
        (has_exposure, quantity_details) tuple
        has_exposure: True if position or ACTIVE order exists
        quantity_details: String describing the exposure
    """
    positions, orders, status_code, error_text = get_schwab_positions()
    
    if positions is None or orders is None:
        print("WARNING: Could not check Schwab exposure")
        print(f"  Status: {status_code}, Error: {error_text}")
        return False, None
    
    # Active order statuses that can still result in a fill
    ACTIVE_STATUSES = {
        "WORKING",
        "PENDING_ACTIVATION",
        "QUEUED",
        "ACCEPTED",
        "AWAITING_PARENT_ORDER",
        "AWAITING_CONDITION",
        "PARTIALLY_FILLED",
    }
    
    # Terminal statuses that never block trading
    TERMINAL_STATUSES = {
        "FILLED",
        "CANCELED",
        "CANCELLED",
        "REPLACED",
        "EXPIRED",
        "REJECTED",
    }
    
    # Check for SPY option positions
    for pos in positions:
        if pos.get("instrument", {}).get("assetType") == "OPTION":
            symbol = pos.get("instrument", {}).get("symbol", "")
            if "SPY" in symbol:
                qty = pos.get("longQuantity", 0)
                if qty > 0:
                    return True, f"Position: {symbol} qty {qty}"
    
    # Check for SPY option ACTIVE orders (only those that can still fill)
    for order in orders:
        status = order.get("status", "")
        order_id = order.get("orderId", "UNKNOWN")
        
        # Skip terminal statuses - these never block trading
        if status in TERMINAL_STATUSES:
            print(f"  [RECONCILIATION] Order {order_id}: status={status} (TERMINAL) → does NOT block")
            continue
        
        legs = order.get("orderLegCollection", [])
        for leg in legs:
            instr = leg.get("instrument", {})
            if instr.get("assetType") == "OPTION":
                symbol = instr.get("symbol", "")
                if "SPY" in symbol:
                    qty = leg.get("quantity", 0)
                    instruction = leg.get("instruction", "")
                    
                    # Check if status is active
                    is_active = status in ACTIVE_STATUSES
                    active_str = "ACTIVE" if is_active else "INACTIVE"
                    
                    print(f"  [RECONCILIATION] Order {order_id}: {instruction} {qty} {symbol} | status={status} ({active_str}) → blocks={is_active}")
                    
                    if is_active:
                        return True, f"Active order: {symbol} qty {qty} status {status}"
    
    return False, None


def reconcile_startup():
    """
    Check Schwab on startup for existing SPY option positions or orders.
    
    SAFE MODE: If broker reconciliation fails, TRADING IS DISABLED
    
    Detects:
    - Existing positions (loads them into current_position if they exist)
    - Quantity > configured cap (sets max_quantity_exceeded lock)
    - Pending orders (alerts user)
    - API errors (enters SAFE MODE)
    
    Returns:
        True if safe to continue trading
        False if critical issues detected
    """
    global current_position, _max_quantity_exceeded, _excess_quantity_details
    global _safe_mode, _safe_mode_reason
    
    print("\n" + "="*70)
    print("🔍 STARTUP RECONCILIATION: Checking Schwab for existing SPY options...")
    print("="*70)
    
    positions, orders, status_code, error_text = get_schwab_positions()

    attempt = 1
    while (
        (positions is None or orders is None)
        and attempt < BROKER_RECONCILE_MAX_ATTEMPTS
        and _is_retryable_broker_error(status_code, error_text)
    ):
        attempt += 1
        print(
            "[RECONCILIATION] Broker query failed "
            f"(attempt {attempt - 1}/{BROKER_RECONCILE_MAX_ATTEMPTS}, status={status_code}). "
            f"Retrying in {BROKER_RECONCILE_RETRY_DELAY_SECONDS:.1f}s..."
        )
        time.sleep(BROKER_RECONCILE_RETRY_DELAY_SECONDS)
        positions, orders, status_code, error_text = get_schwab_positions()
    
    startup_admission = LIVE_BRAIN.evaluate_startup_reconciliation(
        broker_available=positions is not None and orders is not None,
        exposure_quantity=0,
        required_quantity=MAX_OPEN_CONTRACTS,
        has_protective_stop=True,
    )
    # CRITICAL: If broker query fails, ENTER SAFE MODE
    if not startup_admission.allowed:
        print("\n" + "="*70)
        print("❌ BROKER RECONCILIATION FAILED")
        print("="*70)
        print(f"HTTP Status Code: {status_code}")
        print(f"Error Details:")
        print(f"{'-'*70}")
        
        # Print full error response
        if error_text:
            # Try to format as JSON if possible
            try:
                import json
                error_json = json.loads(error_text)
                print(json.dumps(error_json, indent=2))
            except:
                # Print as plain text if not JSON
                print(error_text)
        print(f"{'-'*70}")
        
        print("\n🔒 SAFE MODE ACTIVATED - TRADING DISABLED")
        print("   Cannot verify broker positions")
        print("   Restart bot after fixing the connection issue")
        print("="*70 + "\n")
        
        _safe_mode = True
        _safe_mode_reason = f"HTTP {status_code}: {error_text} (attempts={attempt})"
        return False
    
    # Broker query successful - continue with position checks
    print("✓ Broker reconciliation successful")
    
    # Check for existing SPY option positions
    spy_positions = []
    for pos in positions:
        if pos.get("instrument", {}).get("assetType") == "OPTION":
            symbol = pos.get("instrument", {}).get("symbol", "")
            if "SPY" in symbol:
                qty = pos.get("longQuantity", 0)
                if qty > 0:
                    spy_positions.append((symbol, qty, pos))
    
    # Check for SPY option pending/open orders
    spy_orders = []
    for order in orders:
        if order.get("status") not in ["FILLED", "CANCELLED", "REJECTED"]:
            legs = order.get("orderLegCollection", [])
            for leg in legs:
                instr = leg.get("instrument", {})
                if instr.get("assetType") == "OPTION":
                    symbol = instr.get("symbol", "")
                    if "SPY" in symbol:
                        qty = leg.get("quantity", 0)
                        status = order.get("status", "")
                        spy_orders.append((symbol, qty, status, order))
    
    # Check for critical issue: quantity exceeds configured cap.
    total_qty = sum(qty for _, qty, _ in spy_positions)
    
    startup_admission = LIVE_BRAIN.evaluate_startup_reconciliation(
        broker_available=True,
        exposure_quantity=total_qty,
        required_quantity=MAX_OPEN_CONTRACTS,
        has_protective_stop=True,
    )
    if not startup_admission.allowed:
        print(f"\n❌ CRITICAL: Quantity exceeds maximum!")
        for symbol, qty, pos in spy_positions:
            print(f"   {symbol}: {qty} contracts")
        _max_quantity_exceeded = True
        _excess_quantity_details = f"Schwab has {total_qty} contracts (max {MAX_OPEN_CONTRACTS})"
        print(f"\n🔒 TRADING DISABLED until manually reconciled")
        print(f"   Please close excess position on Schwab manually")
        print("="*70 + "\n")
        return False
    
    # Existing position (qty within allowed cap) - load it
    if total_qty >= 1:
        symbol, qty, pos = spy_positions[0]
        print(f"✓ Found existing SPY option position: {symbol} qty {qty}")
        print(f"   Avg price: {pos.get('averagePrice', 0)}")
        
        # CRITICAL: Check if position has a protective SELL_TO_CLOSE stop
        has_protective_stop = False
        print(f"   [DEBUG] Checking {len(orders)} orders for protective stop...")
        for order in orders:
            order_status = order.get("status", "UNKNOWN")
            strategy = order.get("orderStrategyType", "UNKNOWN")
            order_type = order.get("orderType", "UNKNOWN")
            legs = order.get("orderLegCollection", [])
            
            if legs:
                instr = legs[0].get("instrument", {})
                instr_symbol = instr.get("symbol", "")
                instr_type = instr.get("assetType", "")
                instruction = legs[0].get("instruction", "")
                print(f"   [DEBUG] Order: status={order_status}, strategy={strategy}, type={order_type}, symbol={instr_symbol}, instruction={instruction}")
            
            if order.get("status") not in ["FILLED", "CANCELLED", "REJECTED"]:
                # Check if this is a SELL_TO_CLOSE STOP or LIMIT for the SPY option
                if order.get("orderStrategyType") == "SINGLE":
                    instr = order.get("orderLegCollection", [{}])[0].get("instrument", {})
                    if instr.get("assetType") == "OPTION" and instr.get("symbol") == symbol:
                        instruction = order.get("orderLegCollection", [{}])[0].get("instruction", "")
                        if instruction == "SELL_TO_CLOSE":
                            order_type = order.get("orderType", "")
                            # Only STOP/STOP_LIMIT orders provide downside protection.
                            if order_type in ["STOP", "STOP_LIMIT"]:
                                has_protective_stop = True
                                stop_or_limit_price = order.get("stopPrice") or order.get("price")
                                order_id = order.get("orderId", "")
                                order_type_label = f"{order_type} @ ${stop_or_limit_price}" if stop_or_limit_price else order_type
                                print(f"   ✓ Protective stop found: {order_id} ({order_type_label})")
                                break
        
        if not has_protective_stop:
            print(f"\n❌ CRITICAL: UNPROTECTED BROKER POSITION")
            print(f"   Position exists on Schwab but has no protective stop")
            print(f"   Symbol: {symbol}")
            print(f"   Quantity: {qty}")
            print(f"   Attempting automatic protective-stop recovery...")

            avg_price = float(pos.get("averagePrice") or 0.0)
            recovered_stop_id = None
            recovered_stop_price = None
            if avg_price > 0 and float(qty or 0) > 0:
                recovered_stop_id, recovered_stop_price = _submit_protective_stop(
                    option_symbol=str(symbol),
                    fill_price=float(avg_price),
                    quantity=int(float(qty or 0)),
                )

            if recovered_stop_id:
                print(
                    f"   ✓ Auto-recovery succeeded: protective stop {recovered_stop_id} "
                    f"@ ${float(recovered_stop_price or 0):.2f}"
                )
                has_protective_stop = True
            else:
                print(f"   ✗ Auto-recovery failed; manual action required")
            
            startup_admission = LIVE_BRAIN.evaluate_startup_reconciliation(
                broker_available=True,
                exposure_quantity=total_qty,
                required_quantity=MAX_OPEN_CONTRACTS,
                has_protective_stop=has_protective_stop,
            )
            global _protective_stop_failed, _protective_stop_failure_reason
            if not startup_admission.allowed:
                _protective_stop_failed = True
                _protective_stop_failure_reason = "Existing broker position is unprotected"

                print(f"\n🔒 TRADING DISABLED - MANUAL RESOLUTION REQUIRED")
                print(f"   Option 1: Place protective SELL_TO_CLOSE STOP on Schwab manually")
                print(f"   Option 2: Close the position on Schwab manually")
                print(f"   Option 3: Restart bot after resolving")
                print("="*70 + "\n")
                return False
        
        # Load position if local position doesn't exist
        if current_position is None:
            print(f"   Loading position from Schwab...")
            # Could create Position from Schwab data here if needed
            # For now, just alert user
            print(f"   ℹ️  Local position file is empty - manual load may be needed")
    
    # Pending orders - cancel only actively working orders to clean up account
    if spy_orders:
        print(f"\n⚠️  {len(spy_orders)} pending SPY option order(s):")
        cancelled_count = 0
        for symbol, qty, status, order in spy_orders:
            order_id = order.get("orderId", "")
            print(f"   {symbol}: {qty} qty, status: {status}, ID: {order_id}")
            
            # Only cancel orders that are in "working" state (can be cancelled)
            # Skip REPLACED/EXPIRED as they're already historical
            if status in ["PENDING_ACTIVATION", "ACCEPTED", "QUEUED", "WORKING", "PENDING_REPLACEMENT"]:
                try:
                    # schwab-py signature is cancel_order(order_id, account_hash)
                    cancel_resp = _schwab_client.cancel_order(order_id, _schwab_account_hash)
                    cancel_resp.raise_for_status()
                    print(f"      ✓ Cancelled {status} order {order_id}")
                    cancelled_count += 1
                except Exception as e:
                    print(f"      ⚠️  Could not cancel {status} order {order_id}: {e}")
            else:
                # REPLACED/EXPIRED/CANCELED are historical and cannot be cancelled
                print(f"      ℹ️  Skipping {status} order (already closed)")
        
        if cancelled_count > 0:
            print(f"   ✓ Cleaned up {cancelled_count} active working orders")
        else:
            print(f"   ℹ️  {len(spy_orders)} orders are historical (REPLACED/EXPIRED) - safe to ignore")
    
    # Summary
    if not spy_positions and not spy_orders:
        print("✓ Clean state: No existing SPY option positions or orders")
    
    print("="*70 + "\n")
    return True


# Configuration for order submission
ORDER_SUBMISSION_TIMEOUT_SECONDS = 30  # Wait up to 30 seconds for fill
ORDER_CHECK_INTERVAL_SECONDS = float(os.getenv("ORDER_CHECK_INTERVAL_SECONDS", "0.08"))  # Check fill status every 80ms
ORDER_QUANTITY = MAX_OPEN_CONTRACTS      # Target the configured maximum per trade
ENTRY_LIMIT_MAX_WAIT_SECONDS = float(os.getenv("ENTRY_LIMIT_MAX_WAIT_SECONDS", "1.25"))
ENTRY_MARKET_FALLBACK_MAX_WAIT_SECONDS = float(os.getenv("ENTRY_MARKET_FALLBACK_MAX_WAIT_SECONDS", "1.0"))
ENTRY_MARKET_FALLBACK_ENABLED = str(os.getenv("ENTRY_MARKET_FALLBACK_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}


def normalize_option_tick(price):
    """
    Normalize option limit price to valid Schwab tick size.
    
    Options use tick sizes:
    - $0.01 for options priced at or above $3.00
    - $0.05 for options priced below $3.00
    
    Args:
        price: Raw limit price (may have many decimals)
    
    Returns:
        Normalized price using proper tick
    """
    price_float = float(price)
    
    if price_float >= 3.0:
        # Round to nearest $0.01
        normalized = round(price_float, 2)
    else:
        # Round to nearest $0.05
        normalized = round(price_float * 20) / 20
    
    return normalized


def _extract_execution_price(order):
    """Return canonical broker fill price from execution legs (qty-weighted)."""
    total_qty = 0.0
    total_notional = 0.0

    for activity in (order or {}).get("orderActivityCollection", []) or []:
        for exec_leg in activity.get("executionLegs", []) or []:
            try:
                qty = float(exec_leg.get("quantity") or 0.0)
                px = float(exec_leg.get("price"))
            except (TypeError, ValueError):
                continue
            if qty <= 0:
                continue
            total_qty += qty
            total_notional += qty * px

    if total_qty > 0:
        return total_notional / total_qty

    try:
        px = (order or {}).get("price")
        return float(px) if px is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class Position:
    direction: str
    entry_price: float
    stop_price: float
    target_price: float
    quantity: int
    opened: datetime
    reason: str
    option_symbol: str = ""
    option_entry: float = 0.0
    option_delta: float = 0.0
    feature_payload: str = ""
    option_stop: float = 0.0
    option_initial_stop: float = 0.0
    schwab_order_id: str = ""           # Schwab order ID for live tracking
    schwab_fill_price: float = 0.0      # Actual fill price from Schwab
    schwab_fill_timestamp: str = ""     # When the order filled
    submitted_limit_price: float = 0.0  # Submitted limit price
    # Protective stop order fields
    protective_stop_order_id: str = ""  # Broker-held SELL_TO_CLOSE stop order ID
    protective_stop_price: float = 0.0  # Stop trigger price (-5% of fill)
    protective_stop_status: str = ""    # PENDING, PLACED, FAILED, CANCELED
    protective_stop_restore_count: int = 0  # Number of in-trade restore operations


current_position = None
current_position = load_position(Position)
trade_log = []
LIVE_BRAIN = Brain()

# Submission lock: after HTTP 400 rejection, block further entry attempts
_submission_rejected = False
_rejection_reason = None

# Entry pending lock: after successful submission, block until fill confirmed
_entry_pending = False
_pending_order_id = None

# Max quantity lock: if Schwab shows more than configured SPY option contracts
_max_quantity_exceeded = False
_excess_quantity_details = None

# SAFE MODE: broker reconciliation failed at startup
_safe_mode = False
_safe_mode_reason = None

# Protective stop lock: if protective stop submission failed
_protective_stop_failed = False
_protective_stop_failure_reason = None
_last_unprotected_alert_ts = None
UNPROTECTED_ALERT_COOLDOWN_SECONDS = 120
LAST_OPEN_TRADE_METRICS = {
    "attempted": False,
    "opened": False,
    "block_reason": None,
    "precheck_ms": None,
    "quote_compute_ms": None,
    "submit_order_ms": None,
    "wait_fill_ms": None,
    "market_fallback_submit_ms": None,
    "market_fallback_wait_ms": None,
    "protective_stop_ms": None,
    "persist_ms": None,
    "total_open_trade_ms": None,
    "filled_via": None,
}


def _set_last_open_trade_metrics(metrics):
    global LAST_OPEN_TRADE_METRICS
    LAST_OPEN_TRADE_METRICS = dict(metrics or {})


def get_last_open_trade_metrics():
    return dict(LAST_OPEN_TRADE_METRICS or {})

def _extract_momentum_fields(feature_payload_text):
    """Extract momentum diagnostics persisted at entry from feature payload JSON."""
    if not feature_payload_text:
        return None, None
    try:
        payload = json.loads(feature_payload_text)
        score = payload.get("momentum_freshness_score")
        phase = payload.get("momentum_phase")
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        phase = str(phase).upper() if phase else None
        return score, phase
    except Exception:
        return None, None


def _extract_absorption_score(feature_payload_text, direction=None):
    if not feature_payload_text:
        return None
    try:
        payload = json.loads(feature_payload_text)
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            return None

        score = payload.get("absorption_score")
        if score is not None:
            return float(score)

        side = "put" if str(direction or "").upper() == "PUT" else "call"
        side_obj = payload.get(f"absorption_score_{side}")
        if isinstance(side_obj, dict) and side_obj.get("score") is not None:
            return float(side_obj.get("score"))
        return None
    except Exception:
        return None


def _extract_entry_diagnostic_snapshot(feature_payload_text):
    """Extract entry-time diagnostics from feature payload as compact JSON text."""
    return extract_entry_diagnostic_snapshot(feature_payload_text)


def _record_entry_feature_vector(feature_payload, broker_entry_order_id):
    """Persist the exact entry decision vector through the canonical Memory service."""
    if not feature_payload:
        return None
    return get_memory().record_feature_vector(
        feature_payload,
        source="live_execution",
        correlation_id=str(broker_entry_order_id or "") or None,
    )


def _build_exit_diagnostic_snapshot(*, direction, reason, source, underlying_entry, underlying_exit, option_entry, option_exit):
    """Create exit-time diagnostic snapshot JSON text."""
    try:
        opt_ret_pct = None
        if option_entry and option_exit and float(option_entry) > 0:
            opt_ret_pct = ((float(option_exit) - float(option_entry)) / float(option_entry)) * 100.0
        under_ret = None
        if underlying_entry and underlying_exit and float(underlying_entry) > 0:
            if str(direction).upper() == "CALL":
                under_ret = ((float(underlying_exit) - float(underlying_entry)) / float(underlying_entry)) * 100.0
            else:
                under_ret = ((float(underlying_entry) - float(underlying_exit)) / float(underlying_entry)) * 100.0
        snapshot = {
            "captured_at": datetime.now(EASTERN_TZ).isoformat(),
            "source": source,
            "direction": direction,
            "exit_reason": reason,
            "underlying_entry": underlying_entry,
            "underlying_exit": underlying_exit,
            "underlying_return_pct": round(under_ret, 3) if under_ret is not None else None,
            "option_entry": option_entry,
            "option_exit": option_exit,
            "option_return_pct": round(opt_ret_pct, 3) if opt_ret_pct is not None else None,
        }
        return json.dumps(snapshot)
    except Exception:
        return None


def _guard_exit_reason(reason, option_entry_price, option_exit_price):
    """Compatibility forwarder for the Brain-owned exit-reason decision."""
    guarded = LIVE_BRAIN.normalize_exit_reason(reason, option_entry_price, option_exit_price)
    if guarded != str(reason or "").strip():
        print(f"[EXIT REASON GUARD] Normalized '{reason}' -> '{guarded}'")
    return guarded


def _has_active_protective_stop_order(option_symbol):
    """Return True if a working SELL_TO_CLOSE stop order exists for this option."""
    if not _schwab_client or not _schwab_account_hash or not option_symbol:
        return False

    active_statuses = {
        "PENDING_ACTIVATION",
        "ACCEPTED",
        "QUEUED",
        "WORKING",
        "PENDING_REPLACEMENT",
        "PARTIALLY_FILLED",
        "AWAITING_PARENT_ORDER",
        "AWAITING_CONDITION",
    }

    try:
        resp = _schwab_client.get_orders_for_account(_schwab_account_hash)
        resp.raise_for_status()
        orders = resp.json() if isinstance(resp.json(), list) else []
    except Exception as e:
        print(f"WARNING: Could not verify active protective stop: {e}")
        return False

    for order in orders:
        status = (order.get("status") or "").upper()
        if status not in active_statuses:
            continue

        order_type = (order.get("orderType") or "").upper()
        if order_type not in {"STOP", "STOP_LIMIT", "TRAILING_STOP", "TRAILING_STOP_LIMIT"}:
            continue

        for leg in order.get("orderLegCollection", []) or []:
            inst = leg.get("instrument", {})
            if inst.get("assetType") != "OPTION":
                continue
            if inst.get("symbol") != option_symbol:
                continue
            if (leg.get("instruction") or "").upper() != "SELL_TO_CLOSE":
                continue
            return True

    return False


def _send_unprotected_position_alert(option_symbol, quantity, stop_price):
    """Send throttled emergency SMS when a position is found without active protection."""
    global _last_unprotected_alert_ts

    now = datetime.now().timestamp()
    if _last_unprotected_alert_ts is not None:
        if (now - _last_unprotected_alert_ts) < UNPROTECTED_ALERT_COOLDOWN_SECONDS:
            return

    details = (
        f"Open SPY option has no active protective exit order.\n"
        f"Symbol: {option_symbol or 'N/A'} | Qty: {int(quantity or 0)}\n"
        f"Intended stop: ${float(stop_price or 0.0):.2f}"
    )
    send_emergency_alert("UNPROTECTED SPY OPTION POSITION", details)
    _last_unprotected_alert_ts = now


def in_trade():
    """Check if a position is currently open."""
    global current_position

    if current_position is None:
        persisted = load_position(Position)
        if persisted is not None:
            current_position = persisted

    return current_position is not None


def reconcile_with_schwab():
    """
    Verify local position state matches Schwab account state.
    
    Returns:
        (is_reconciled, message) - True if states match, False if mismatch
        Blocks new trading if mismatch detected.
    """
    if not _schwab_client:
        return False, "ERROR: Schwab client not configured"
    
    if not current_position:
        return True, "No local position to reconcile"
    
    try:
        # Check Schwab for open positions and recent orders
        positions, orders, status_code, error_text = get_schwab_positions()
        if positions is None or orders is None:
            return False, f"Reconciliation error: HTTP {status_code} {error_text}"
        
        # Check if Schwab has matching position
        local_order_id = current_position.schwab_order_id
        
        schwab_has_order = any(
            str(o.get("orderId")) == str(local_order_id) 
            for o in orders
        )
        
        schwab_has_position = any(
            str(p.get("instrument", {}).get("symbol")) == current_position.option_symbol
            for p in positions
            if p.get("instrument", {}).get("assetType") == "OPTION"
        )
        
        # If local position exists, Schwab should have either order or position
        if not (schwab_has_order or schwab_has_position):
            return False, f"Mismatch: Local position {local_order_id} not found on Schwab"
        
        return True, "Reconciliation OK"
        
    except Exception as e:
        return False, f"Reconciliation error: {e}"


def _sync_position_with_broker(current_price, force: bool = False):
    """Reconcile local position with broker and auto-heal stale open positions.

    If local state shows an open position but Schwab has no matching open option
    position, clear local state and log a reconciled exit (if a SELL_TO_CLOSE fill
    is found in recent broker orders).
    """
    global current_position, _protective_stop_failed, _protective_stop_failure_reason, _last_broker_sync_epoch

    if not current_position or not _schwab_client:
        return

    if not force:
        now_epoch = time.time()
        min_interval = max(0.25, float(BROKER_SYNC_MIN_INTERVAL_SECONDS or 2.0))
        if (now_epoch - float(_last_broker_sync_epoch or 0.0)) < min_interval:
            return
        _last_broker_sync_epoch = now_epoch

    positions, orders, status_code, error_text = get_schwab_positions()
    if positions is None or orders is None:
        print(f"WARNING: Broker sync unavailable (status={status_code}): {error_text}")
        return

    symbol = current_position.option_symbol

    # Broker still has the option position: keep managing normally.
    for pos in positions:
        inst = pos.get("instrument", {})
        if inst.get("assetType") == "OPTION" and inst.get("symbol") == symbol:
            if float(pos.get("longQuantity", 0) or 0) > 0:
                return

    # No broker position found for local symbol: local state is stale.
    print(f"\n⚠️  BROKER RECONCILIATION: Local position stale for {symbol}")
    print("   Schwab shows no open position. Clearing local state.")

    def _order_time(order):
        return order.get("closeTime") or order.get("enteredTime") or ""

    def _is_exit_order_already_logged(exit_order_id):
        if not exit_order_id:
            return False
        db_path = Path("data/mcleod_alpha.db")
        if not db_path.exists():
            return False
        try:
            with sqlite3.connect(str(db_path)) as con:
                cols = [r[1] for r in con.execute("PRAGMA table_info(trade_log)").fetchall()]
                if "broker_exit_order_id" not in cols:
                    return False
                row = con.execute(
                    "SELECT 1 FROM trade_log WHERE broker_exit_order_id = ? LIMIT 1",
                    (str(exit_order_id),),
                ).fetchone()
                return row is not None
        except Exception:
            return False

    def _is_entry_order_already_logged(entry_order_id):
        if not entry_order_id:
            return False
        db_path = Path("data/mcleod_alpha.db")
        if not db_path.exists():
            return False
        try:
            with sqlite3.connect(str(db_path)) as con:
                cols = [r[1] for r in con.execute("PRAGMA table_info(trade_log)").fetchall()]
                if "broker_entry_order_id" not in cols:
                    return False
                row = con.execute(
                    "SELECT 1 FROM trade_log WHERE broker_entry_order_id = ? LIMIT 1",
                    (str(entry_order_id),),
                ).fetchone()
                return row is not None
        except Exception:
            return False

    broker_exit_price = None
    broker_exit_time = datetime.now().isoformat()
    broker_exit_order_id = None
    entry_id = str(getattr(current_position, "schwab_order_id", "") or "")
    entry_time_hint = str(getattr(current_position, "schwab_fill_timestamp", "") or current_position.opened.isoformat())
    broker_entry_time = entry_time_hint

    # Build candidate SELL_TO_CLOSE fills for this symbol and choose the earliest
    # unlogged fill that occurs after this position's entry time.
    exit_candidates = []
    for order in orders:
        status = (order.get("status") or "").upper()
        if status != "FILLED":
            continue
        for leg in order.get("orderLegCollection", []) or []:
            inst = leg.get("instrument", {})
            if inst.get("assetType") != "OPTION":
                continue
            if inst.get("symbol") != symbol:
                continue
            if (leg.get("instruction") or "").upper() != "SELL_TO_CLOSE":
                continue
            candidate_id = str(order.get("orderId") or "")
            if _is_exit_order_already_logged(candidate_id):
                continue
            candidate_time = _order_time(order)
            if candidate_time and entry_time_hint and candidate_time < entry_time_hint:
                continue
            exit_candidates.append((candidate_time, order))

    if exit_candidates:
        exit_candidates.sort(key=lambda item: item[0] or "")
        matched_exit = exit_candidates[0][1]
        broker_exit_order_id = matched_exit.get("orderId")
        broker_exit_price = _extract_execution_price(matched_exit)
        broker_exit_time = _order_time(matched_exit) or broker_exit_time
    else:
        print(
            "WARNING: Broker shows no position but no matching post-entry "
            f"SELL_TO_CLOSE fill was found for {symbol}; preserving local state."
        )
        return

    # If broker entry order ID is known, prefer exact BUY_TO_OPEN execution price.
    broker_entry_price = float(current_position.option_entry or 0.0)
    if entry_id:
        for order in orders:
            if str(order.get("orderId")) != entry_id:
                continue
            broker_entry_price = float(_extract_execution_price(order) or broker_entry_price)
            broker_entry_time = _order_time(order) or broker_entry_time
            break
    else:
        # Recover entry order from broker fills if local order id was not persisted.
        entry_candidates = []
        for order in orders:
            status = (order.get("status") or "").upper()
            if status != "FILLED":
                continue
            for leg in order.get("orderLegCollection", []) or []:
                inst = leg.get("instrument", {})
                if inst.get("assetType") != "OPTION":
                    continue
                if inst.get("symbol") != symbol:
                    continue
                if (leg.get("instruction") or "").upper() != "BUY_TO_OPEN":
                    continue
                candidate_id = str(order.get("orderId") or "")
                if _is_entry_order_already_logged(candidate_id):
                    continue
                candidate_time = _order_time(order)
                if entry_time_hint and candidate_time and candidate_time < entry_time_hint:
                    continue
                if broker_exit_time and candidate_time and candidate_time > broker_exit_time:
                    continue
                entry_candidates.append((candidate_time, order))

        if entry_candidates:
            entry_candidates.sort(key=lambda item: item[0] or "")
            matched_entry = entry_candidates[0][1]
            entry_id = str(matched_entry.get("orderId") or "")
            broker_entry_price = float(_extract_execution_price(matched_entry) or broker_entry_price)
            broker_entry_time = _order_time(matched_entry) or broker_entry_time

    option_entry_price = float(broker_entry_price or 0.0)
    option_exit_price = float(broker_exit_price or option_entry_price or 0.0)
    qty = int(current_position.quantity or 0)
    option_pnl_dollars = (option_exit_price - option_entry_price) * qty * 100
    option_pnl_pct = ((option_exit_price - option_entry_price) / option_entry_price) if option_entry_price > 0 else 0.0
    momentum_freshness_score, momentum_phase = _extract_momentum_fields(getattr(current_position, "feature_payload", ""))
    absorption_score = _extract_absorption_score(getattr(current_position, "feature_payload", ""), current_position.direction)
    entry_diagnostic_snapshot = _extract_entry_diagnostic_snapshot(getattr(current_position, "feature_payload", ""))
    exit_diagnostic_snapshot = _build_exit_diagnostic_snapshot(
        direction=current_position.direction,
        reason="BROKER_RECONCILED_EXIT",
        source="LIVE_RECONCILED",
        underlying_entry=current_position.entry_price,
        underlying_exit=current_position.entry_price,
        option_entry=option_entry_price,
        option_exit=option_exit_price,
    )

    try:
        try:
            log_trade_diagnostic_event(
                event_type="EXIT",
                direction=current_position.direction,
                option_symbol=current_position.option_symbol,
                source="LIVE_RECONCILED",
                snapshot=exit_diagnostic_snapshot,
            )
        except Exception as e:
            print(f"WARNING: Could not persist live EXIT diagnostic snapshot: {e}")

        # For broker-reconciled exits we may not have exact underlying exit price,
        # so persist option-based realized P&L as the canonical pnl value.
        safe_log_trade(
            entry_time=broker_entry_time or current_position.opened.isoformat(),
            exit_time=broker_exit_time,
            direction=current_position.direction,
            entry_price=current_position.entry_price,
            exit_price=current_position.entry_price,
            pnl=option_pnl_dollars,
            exit_reason="BROKER_RECONCILED_EXIT",
            feature_payload=current_position.feature_payload,
            option_symbol=current_position.option_symbol,
            option_entry=option_entry_price,
            option_exit=option_exit_price,
            option_quantity=qty,
            option_delta=current_position.option_delta,
            option_return=option_pnl_pct,
            option_pnl_dollars=option_pnl_dollars,
            option_pnl_pct=option_pnl_pct,
            broker_entry_order_id=entry_id or None,
            broker_exit_order_id=str(broker_exit_order_id) if broker_exit_order_id else None,
            momentum_freshness_score=momentum_freshness_score,
            momentum_phase=momentum_phase,
            absorption_score=absorption_score,
            entry_diagnostic_snapshot=entry_diagnostic_snapshot,
            exit_diagnostic_snapshot=exit_diagnostic_snapshot,
        )
        if broker_exit_order_id:
            print(f"   Logged reconciled exit from broker order {broker_exit_order_id}")
    except Exception as log_exc:
        print(f"WARNING: Could not log reconciled exit: {log_exc}")

    clear_position()
    current_position = None
    # The unprotected position has now been reconciled and cleared, so remove
    # the lock that blocks future entries.
    _protective_stop_failed = False
    _protective_stop_failure_reason = None
    print("✓ Cleared stale local position after broker reconciliation")
    print("✓ Protective stop failure lock cleared after broker reconciliation")


def cleanup_phantom_position():
    """
    SAFE: Only call this after confirming Schwab has no matching order/position.
    
    Removes local position file when Schwab confirms no corresponding order/position exists.
    Used to recover from phantom position states.
    """
    global current_position
    
    if not current_position:
        return True
    
    try:
        clear_position()
        current_position = None
        print("✓ Phantom position cleaned up (verified with Schwab)")
        return True
    except Exception as e:
        print(f"ERROR cleaning up position: {e}")
        return False


def _calculate_protective_stop_price(fill_price):
    """
    Calculate protective stop price at -5% of option fill price.
    
    Args:
        fill_price: Confirmed option fill price
        
    Returns:
        Stop trigger price normalized to valid option tick
    """
    if fill_price <= 0:
        return 0.0
    
    stop_raw = LIVE_BRAIN.initial_protective_stop(fill_price)
    
    # Normalize to valid tick
    stop_normalized = normalize_option_tick(stop_raw)
    
    print(f"   Protective Stop Calculation: {fill_price:.2f} * 95% = {stop_raw:.6f} → {stop_normalized:.2f}")
    return stop_normalized


def _protective_stop_order_prices(stop_price):
    """Return the normalized broker STOP_LIMIT trigger and loss-floor limit."""
    limit_price = normalize_option_tick(float(stop_price))
    tick_size = 0.01 if limit_price >= 3.0 else 0.05
    return normalize_option_tick(limit_price + tick_size), limit_price


def _stop_reason_for_active_stop(position):
    """Compatibility forwarder for the Brain-owned active stop-tier decision."""
    return LIVE_BRAIN._active_stop_reason(position)


def _submit_protective_stop(
    option_symbol,
    fill_price,
    quantity,
    stop_price_override=None,
    existing_stop_order_id=None,
):
    """
    Submit broker-held SELL_TO_CLOSE protective stop order.
    
    Uses STOP_LIMIT order type with calculated trigger at -5% of fill.
    
    Args:
        option_symbol: Exact Schwab option symbol (e.g., "SPY 260724C00754000")
        fill_price: Confirmed entry fill price
        quantity: Filled quantity
        stop_price_override: Optional explicit stop trigger to submit
        
    Returns:
        (order_id, stop_price) tuple on success
        (None, None) on failure
    """
    global _protective_stop_failed, _protective_stop_failure_reason
    
    if not _schwab_client or not _schwab_account_hash:
        print("ERROR: Schwab client not configured for protective stop submission")
        _protective_stop_failed = True
        _protective_stop_failure_reason = "Client not configured"
        return None, None
    
    stop_price = (
        normalize_option_tick(float(stop_price_override))
        if stop_price_override is not None
        else _calculate_protective_stop_price(fill_price)
    )
    if stop_price <= 0:
        print("ERROR: Invalid protective stop price calculated")
        _protective_stop_failed = True
        _protective_stop_failure_reason = "Invalid stop price"
        return None, None

    # STOP_LIMIT requires a limit; set it slightly below stop to improve fill odds.
    stop_limit_price = normalize_option_tick(stop_price * 0.99)

    existing_protective_stop = (str(existing_stop_order_id), 0.0) if existing_stop_order_id else None

    def _submit_stop_limit_once(target_stop_price):
        """Submit one STOP_LIMIT protective order and return extracted order_id or None."""
        target_stop_price = normalize_option_tick(float(target_stop_price))
        target_limit_price = normalize_option_tick(target_stop_price * 0.99)

        from schwab.orders.generic import OrderBuilder
        from schwab.orders.common import OptionInstruction, Session, Duration, OrderType, OrderStrategyType

        order = (
            OrderBuilder()
            .set_session(Session.NORMAL)
            .set_duration(Duration.DAY)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .set_order_type(OrderType.STOP_LIMIT)
            .set_stop_price(str(target_stop_price))
            .set_price(str(target_limit_price))
            .add_option_leg(OptionInstruction.SELL_TO_CLOSE, option_symbol, quantity)
        )

        response = _schwab_client.place_order(_schwab_account_hash, order)
        response.raise_for_status()

        order_id = None
        if "Location" in response.headers:
            location = response.headers["Location"]
            parts = location.split("/")
            if "orders" in parts:
                orders_idx = parts.index("orders")
                if orders_idx + 1 < len(parts):
                    potential_id = parts[orders_idx + 1]
                    if potential_id and potential_id != _schwab_account_number:
                        order_id = potential_id
            if not order_id and len(parts) > 0:
                potential_id = parts[-1]
                if potential_id and potential_id != _schwab_account_number:
                    order_id = potential_id
            if order_id == _schwab_account_number:
                order_id = None

        if not order_id:
            return None, target_stop_price, target_limit_price, order

        return order_id, target_stop_price, target_limit_price, order
    
    try:
        # Detect any currently working protective stop for this symbol.
        # We do NOT cancel it up front. We submit the replacement first,
        # then retire the old stop only after the new one is confirmed.
        active_statuses = {
            "PENDING_ACTIVATION",
            "ACCEPTED",
            "QUEUED",
            "WORKING",
            "PENDING_REPLACEMENT",
            "PARTIALLY_FILLED",
            "AWAITING_PARENT_ORDER",
            "AWAITING_CONDITION",
        }
        try:
            existing_resp = _schwab_client.get_orders_for_account(_schwab_account_hash)
            existing_resp.raise_for_status()
            existing_orders = existing_resp.json() if isinstance(existing_resp.json(), list) else []
            for existing in existing_orders:
                status = (existing.get("status") or "").upper()
                if status not in active_statuses:
                    continue

                legs = existing.get("orderLegCollection", []) or []
                if not legs:
                    continue

                leg0 = legs[0]
                inst = leg0.get("instrument", {})
                if inst.get("assetType") != "OPTION":
                    continue
                if inst.get("symbol") != option_symbol:
                    continue
                if leg0.get("instruction") != "SELL_TO_CLOSE":
                    continue

                existing_type = (existing.get("orderType") or "").upper()
                existing_id = str(existing.get("orderId") or "")

                # If a protective stop already exists, reuse if it matches target.
                # Otherwise, remember it so we can cancel it only after the new
                # protective stop is successfully accepted by Schwab.
                if existing_type in {"STOP", "STOP_LIMIT"} and existing_id:
                    existing_stop = existing.get("stopPrice") or existing.get("price") or 0
                    try:
                        existing_stop = float(existing_stop)
                    except (TypeError, ValueError):
                        existing_stop = 0.0

                    if abs(existing_stop - float(stop_price)) < 0.005:
                        print(f"✓ Existing protective stop already active: {existing_id} @ ${existing_stop:.2f}")
                        return existing_id, float(existing_stop)

                    print(
                        f"   Will replace protective stop {existing_id}: "
                        f"${existing_stop:.2f} → ${float(stop_price):.2f}"
                    )
                    existing_protective_stop = (existing_id, float(existing_stop))

                # Cancel working SELL_TO_CLOSE LIMIT to avoid oversold rejection.
                if existing_type == "LIMIT" and existing_id:
                    print(f"   Canceling conflicting SELL_TO_CLOSE LIMIT {existing_id} before stop submission")
                    cancel_resp = _schwab_client.cancel_order(existing_id, _schwab_account_hash)
                    cancel_resp.raise_for_status()
        except Exception as order_cleanup_exc:
            print(f"WARNING: Could not pre-clean conflicting exit orders: {order_cleanup_exc}")

        order_id, submitted_stop_price, submitted_limit_price, order = _submit_stop_limit_once(stop_price)
        
        if not order_id:
            print("WARNING: No order ID returned while submitting replacement stop")

            _protective_stop_failed = True
            _protective_stop_failure_reason = "No order ID returned"
            return None, None
        
        print(f"\n✓ PROTECTIVE STOP SUBMITTED to Schwab")
        print(f"   Order ID: {order_id}")
        print(f"   Type: SELL_TO_CLOSE STOP_LIMIT")
        print(f"   Symbol: {option_symbol}")
        print(f"   Quantity: {quantity}")
        print(f"   Stop Price: ${submitted_stop_price:.2f}")
        print(f"   Limit Price: ${submitted_limit_price:.2f}")
        import json
        payload_str = json.dumps(order.__dict__, default=str)
        print(f"   Payload: {sanitize_for_logging(payload_str)}")

        _audit_bot_order(order_id, "PROTECTIVE_STOP")

        # Only after the new stop is confirmed do we retire the old one.
        if existing_protective_stop:
            existing_id, existing_stop = existing_protective_stop
            try:
                if existing_id != order_id:
                    print(
                        f"   Canceling superseded protective stop {existing_id} "
                        f"after new stop confirmation"
                    )
                    cancel_resp = _schwab_client.cancel_order(existing_id, _schwab_account_hash)
                    cancel_resp.raise_for_status()
                    print(f"   ✓ Superseded protective stop canceled: {existing_id}")
            except Exception as cancel_exc:
                print(
                    f"   WARNING: New stop is live but old stop {existing_id} "
                    f"could not be canceled: {cancel_exc}"
                )
        
        return order_id, submitted_stop_price
        
    except Exception as e:
        error_msg = str(e)
        status_code = getattr(e, 'status_code', None)
        response_text = None
        if hasattr(e, 'response') and e.response is not None:
            if status_code is None:
                status_code = getattr(e.response, 'status_code', None)
            try:
                response_text = e.response.text
            except Exception:
                response_text = str(e.response)
        
        print(f"\n❌ PROTECTIVE STOP SUBMISSION FAILED")
        print(f"   Exception: {error_msg}")
        if status_code:
            print(f"   HTTP Status: {status_code}")
        if response_text:
            print(f"   Response: {response_text}")
        
        _protective_stop_failed = True
        _protective_stop_failure_reason = f"Submission failed: {error_msg}"
        return None, None


def _cancel_protective_stop(order_id):
    """
    Cancel the broker-held protective stop order.
    
    Args:
        order_id: Protective stop order ID to cancel
        
    Returns:
        True if cancellation was successful
        False otherwise
    """
    if not _schwab_client or not _schwab_account_hash or not order_id:
        print("WARNING: Cannot cancel protective stop - client or order ID not available")
        return False
    
    try:
        response = _schwab_client.cancel_order(
            order_id,
            _schwab_account_hash
        )
        
        response.raise_for_status()
        print(f"\n✓ PROTECTIVE STOP CANCELED")
        print(f"   Order ID: {order_id}")
        return True
        
    except Exception as e:
        print(f"\nWARNING: Protective stop cancellation failed")
        print(f"   Order ID: {order_id}")
        print(f"   Error: {e}")
        return False


def _submit_option_order(option_symbol, direction, limit_price, quantity):
    """
    Submit actual option order to Schwab using official schwab-py builders.
    
    Uses exact option symbol from Schwab chain response (no re-parsing).
    Applies submission lock after HTTP 400 rejection.
    
    Args:
        option_symbol: Exact option symbol from Schwab (e.g., "SPY 260724C00754000")
        direction: "CALL" or "PUT" 
        limit_price: Limit price (already normalized to valid tick)
        quantity: Number of contracts (should be 1)
    
    Returns:
        order_id: Schwab order ID if submitted successfully
        None: if submission failed or locked
    """
    global _submission_rejected, _rejection_reason
    
    # Check submission lock
    if _submission_rejected:
        print(f"\n🔒 LIVE ENTRY DISABLED AFTER REJECTION")
        print(f"   Reason: {_rejection_reason}")
        print(f"   Restart bot to clear lock")
        return None
    
    if not _schwab_client or not _schwab_account_hash:
        print("ERROR: Schwab client or account hash not configured")
        return None

    if int(quantity) != MAX_OPEN_CONTRACTS:
        print(
            f"ERROR: Entry quantity {quantity} does not match the configured "
            f"contract limit {MAX_OPEN_CONTRACTS}"
        )
        return None
    
    try:
        from schwab.orders.options import option_buy_to_open_limit
        import json
        
        # Use exact option symbol from Schwab (no reconstruction)
        print(f"\n{'='*70}")
        print(f"🔴 LIVE ORDER SUBMITTING to Schwab")
        print(f"{'='*70}")
        print(f"Option Symbol (exact): {repr(option_symbol)}")
        print(f"Direction: {direction}")
        print(f"Quantity: {quantity}")
        print(f"Limit Price: {limit_price:.2f}")
        print(f"Account Hash Length: {len(_schwab_account_hash)}")
        
        # Normalize limit price to valid option tick
        normalized_price = normalize_option_tick(limit_price)
        
        # Build order using schwab-py's official builder
        # This creates the order with all required fields:
        # - BUY_TO_OPEN instruction
        # - OPTION asset type
        # - LIMIT order type
        # - NORMAL session
        # - DAY duration
        # - SINGLE strategy
        try:
            order = option_buy_to_open_limit(
                option_symbol,    # Exact symbol from chain
                quantity,
                str(normalized_price)
            )
        except Exception as e:
            print(f"ERROR building order with schwab-py builder: {e}")
            import traceback
            traceback.print_exc()
            return None
        
        # Display the builder-generated order structure
        print(f"\nBuilder-generated order structure:")
        try:
            # Try to access order dict representation
            if hasattr(order, '__dict__'):
                sanitized = sanitize_for_logging(json.dumps(order.__dict__, indent=2, default=str))
                print(sanitized)
            else:
                print(f"  Order type: {type(order)}")
                print(f"  {repr(order)}")
        except Exception as e:
            print(f"  (Could not serialize builder output: {e})")
        
        print(f"\nSubmitting to Schwab account (hash length: {len(_schwab_account_hash)})")
        
        # Submit order using account HASH (not account number)
        try:
            resp = _schwab_client.place_order(
                _schwab_account_hash,
                order
            )
        except Exception as e:
            print(f"ERROR calling place_order: {e}")
            import traceback
            traceback.print_exc()
            return None
        
        # Handle HTTP 400 errors
        if resp.status_code not in [200, 201]:
            print(f"\n" + "="*70)
            print(f"❌ SCHWAB API ERROR - Order Submission Failed")
            print(f"="*70)
            print(f"HTTP Status Code: {resp.status_code}")
            print(f"Option Symbol (exact): {repr(option_symbol)}")
            print(f"Normalized Price: {normalized_price:.2f}")
            print(f"Account Hash Length: {len(_schwab_account_hash)}")
            
            print(f"\nComplete Response Body (no truncation):")
            print(f"{'-'*70}")
            
            # Get full response text without truncation
            full_response = resp.text if resp.text else "(empty response body)"
            
            # Try to pretty-print JSON if it is JSON
            try:
                resp_json = resp.json()
                sanitized_response = sanitize_for_logging(json.dumps(resp_json, indent=2))
                print(sanitized_response)
            except:
                # Not JSON, print as-is (sanitized)
                sanitized_response = sanitize_for_logging(full_response)
                print(sanitized_response)
            
            print(f"{'-'*70}")
            
            # Set submission lock on HTTP 400
            if resp.status_code == 400:
                _submission_rejected = True
                _rejection_reason = full_response or "HTTP 400 - Validation error"
                print(f"\n🔒 SUBMISSION LOCK ACTIVATED (HTTP 400)")
                print(f"   No further entry attempts until restart")
                print(f"   Error: {_rejection_reason}")
            
            print(f"\nSensitive data masked: API keys, tokens, and credentials")
            print(f"Contact Schwab support with HTTP {resp.status_code} and details above")
            print(f"="*70)
            return None
        
        # Extract order ID from response headers or body
        order_id = None
        
        if "Location" in resp.headers:
            # Location header format: /v1/accounts/{hash}/orders/{orderId}
            location = resp.headers["Location"]
            print(f"[DEBUG] Location header: {location}")
            parts = location.split("/")
            print(f"[DEBUG] Location parts: {parts}")
            
            # Look for order ID - it should be after "orders/" in the path
            if "orders" in parts:
                orders_idx = parts.index("orders")
                if orders_idx + 1 < len(parts):
                    potential_id = parts[orders_idx + 1]
                    if potential_id and potential_id != _schwab_account_number:
                        order_id = potential_id
                        print(f"[DEBUG] Found order_id after 'orders/': {order_id}")
                else:
                    # Last part but no actual order ID
                    print(f"[DEBUG] 'orders' in path but no ID following it")
            
            # If we couldn't find it that way, try last part (fallback)
            if not order_id and len(parts) > 0:
                potential_id = parts[-1]
                if potential_id and potential_id != _schwab_account_number:
                    order_id = potential_id
                    print(f"[DEBUG] Using last part as order_id: {order_id}")
        
        if not order_id:
            # Fallback: try to get from response body
            try:
                resp_data = resp.json() if resp.text else {}
                order_id = resp_data.get("id") or resp_data.get("orderId")
                print(f"[DEBUG] Got order_id from response body: {order_id}")
            except Exception as parse_err:
                print(f"[DEBUG] Could not parse response body: {parse_err}")
        
        if order_id and order_id == _schwab_account_number:
            print(f"[WARNING] Extracted account number as order ID (malformed Location header?)")
            order_id = None
        
        if order_id:
            print(f"\n✓ Order submitted successfully with ID: {order_id}")
            print(f"{'='*70}\n")
            _audit_bot_order(order_id, "ENTRY")
            return order_id
        else:
            print("WARNING: Could not extract order ID from response, assuming submitted")
            return "pending"
        
    except Exception as e:
        print(f"ERROR submitting order: {e}")
        import traceback
        traceback.print_exc()
        return None


def _submit_option_exit_market_order(option_symbol, quantity):
    """Submit a broker SELL_TO_CLOSE market order for an open option position."""
    if not _schwab_client or not _schwab_account_hash:
        print("ERROR: Schwab client or account hash not configured for exit order")
        return None

    try:
        from schwab.orders.generic import OrderBuilder
        from schwab.orders.common import OptionInstruction, Session, Duration, OrderType, OrderStrategyType

        order = (
            OrderBuilder()
            .set_session(Session.NORMAL)
            .set_duration(Duration.DAY)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .set_order_type(OrderType.MARKET)
            .add_option_leg(OptionInstruction.SELL_TO_CLOSE, option_symbol, quantity)
        )

        response = _schwab_client.place_order(_schwab_account_hash, order)
        response.raise_for_status()

        order_id = None
        if "Location" in response.headers:
            location = response.headers["Location"]
            parts = location.split("/")
            if "orders" in parts:
                idx = parts.index("orders")
                if idx + 1 < len(parts):
                    potential = parts[idx + 1]
                    if potential and potential != _schwab_account_number:
                        order_id = potential
            if not order_id and parts:
                potential = parts[-1]
                if potential and potential != _schwab_account_number:
                    order_id = potential

        if not order_id:
            print("WARNING: Exit order submitted but no order ID returned")
            return None

        print(f"✓ EXIT ORDER SUBMITTED: SELL_TO_CLOSE MARKET {option_symbol} x{quantity} (Order {order_id})")
        _audit_bot_order(order_id, "EXIT_MARKET")
        return order_id
    except Exception as e:
        print(f"ERROR submitting exit market order: {e}")
        return None


def _submit_option_entry_market_order(option_symbol, quantity):
    """Submit a broker BUY_TO_OPEN market order for fast entry fallback."""
    if not _schwab_client or not _schwab_account_hash:
        print("ERROR: Schwab client or account hash not configured for entry market order")
        return None

    try:
        from schwab.orders.generic import OrderBuilder
        from schwab.orders.common import OptionInstruction, Session, Duration, OrderType, OrderStrategyType

        order = (
            OrderBuilder()
            .set_session(Session.NORMAL)
            .set_duration(Duration.DAY)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .set_order_type(OrderType.MARKET)
            .add_option_leg(OptionInstruction.BUY_TO_OPEN, option_symbol, quantity)
        )

        response = _schwab_client.place_order(_schwab_account_hash, order)
        response.raise_for_status()

        order_id = None
        if "Location" in response.headers:
            location = response.headers["Location"]
            parts = location.split("/")
            if "orders" in parts:
                idx = parts.index("orders")
                if idx + 1 < len(parts):
                    potential = parts[idx + 1]
                    if potential and potential != _schwab_account_number:
                        order_id = potential
            if not order_id and parts:
                potential = parts[-1]
                if potential and potential != _schwab_account_number:
                    order_id = potential

        if not order_id:
            print("WARNING: Entry market order submitted but no order ID returned")
            return None

        print(f"✓ ENTRY ORDER SUBMITTED: BUY_TO_OPEN MARKET {option_symbol} x{quantity} (Order {order_id})")
        _audit_bot_order(order_id, "ENTRY_MARKET")
        return order_id
    except Exception as e:
        print(f"ERROR submitting entry market order: {e}")
        return None


def _submit_option_exit_limit_order(option_symbol, quantity, limit_price):
    """Submit a broker SELL_TO_CLOSE limit order for an open option position."""
    if not _schwab_client or not _schwab_account_hash:
        print("ERROR: Schwab client or account hash not configured for limit exit order")
        return None

    try:
        from schwab.orders.generic import OrderBuilder
        from schwab.orders.common import OptionInstruction, Session, Duration, OrderType, OrderStrategyType

        normalized_limit = normalize_option_tick(float(limit_price))
        order = (
            OrderBuilder()
            .set_session(Session.NORMAL)
            .set_duration(Duration.DAY)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .set_order_type(OrderType.LIMIT)
            .set_price(str(normalized_limit))
            .add_option_leg(OptionInstruction.SELL_TO_CLOSE, option_symbol, quantity)
        )

        response = _schwab_client.place_order(_schwab_account_hash, order)
        response.raise_for_status()

        order_id = None
        if "Location" in response.headers:
            location = response.headers["Location"]
            parts = location.split("/")
            if "orders" in parts:
                idx = parts.index("orders")
                if idx + 1 < len(parts):
                    potential = parts[idx + 1]
                    if potential and potential != _schwab_account_number:
                        order_id = potential
            if not order_id and parts:
                potential = parts[-1]
                if potential and potential != _schwab_account_number:
                    order_id = potential

        if not order_id:
            print("WARNING: Limit exit order submitted but no order ID returned")
            return None

        print(
            f"✓ EXIT ORDER SUBMITTED: SELL_TO_CLOSE LIMIT {option_symbol} x{quantity} "
            f"@ ${normalized_limit:.2f} (Order {order_id})"
        )
        _audit_bot_order(order_id, "EXIT_LIMIT")
        return order_id
    except Exception as e:
        print(f"ERROR submitting exit limit order: {e}")
        return None


def _fetch_option_quote_snapshot(option_symbol):
    """Return best-effort option quote levels plus freshness metadata."""
    if not _schwab_client or not option_symbol:
        return {}
    try:
        resp = _schwab_client.get_quote(option_symbol)
        resp.raise_for_status()
        payload = resp.json() or {}
        symbol_blob = payload.get(option_symbol) or {}
        quote = symbol_blob.get("quote") or {}
        regular = symbol_blob.get("regular") or {}
        extended = symbol_blob.get("extended") or {}
        out = {}
        for key, value in {
            "bid": quote.get("bidPrice") or quote.get("bid"),
            "ask": quote.get("askPrice") or quote.get("ask"),
            "mark": quote.get("mark"),
            "last": quote.get("lastPrice") or regular.get("regularMarketLastPrice") or extended.get("lastPrice"),
        }.items():
            try:
                if value is not None and float(value) > 0:
                    out[key] = float(value)
            except (TypeError, ValueError):
                continue

        quote_epoch_seconds = _extract_quote_epoch_seconds(payload, symbol_blob, quote, regular, extended)
        quote_age_seconds = None
        quote_as_of = None
        if quote_epoch_seconds is not None:
            quote_age_seconds = max(0.0, time.time() - quote_epoch_seconds)
            quote_as_of = datetime.fromtimestamp(quote_epoch_seconds, tz=timezone.utc).isoformat()

        bid = float(out.get("bid", 0.0) or 0.0)
        ask = float(out.get("ask", 0.0) or 0.0)
        spread = None
        spread_pct = None
        mid = None
        if bid > 0 and ask > 0 and ask >= bid:
            spread = round(ask - bid, 4)
            mid = round((ask + bid) / 2.0, 4)
            if mid > 0:
                spread_pct = round(((ask - bid) / mid) * 100.0, 2)

        out["quote_age_seconds"] = round(float(quote_age_seconds), 1) if quote_age_seconds is not None else None
        out["quote_as_of"] = quote_as_of
        out["quote_spread"] = spread
        out["quote_spread_pct"] = spread_pct
        out["quote_mid"] = mid
        return out
    except Exception as e:
        print(f"WARNING: Could not fetch option quote levels: {e}")
        return {}


def _fetch_option_quote_levels(option_symbol):
    """Return best-effort option quote levels for exit pricing."""
    snapshot = _fetch_option_quote_snapshot(option_symbol)
    return {key: value for key, value in snapshot.items() if key in {"bid", "ask", "mark", "last"}}


def _compute_fast_exit_limit_price(option_symbol, fallback_price):
    """Compute a fast-fill, near-market limit price for manual exit."""
    levels = _fetch_option_quote_levels(option_symbol)
    bid = float(levels.get("bid", 0.0) or 0.0)
    ask = float(levels.get("ask", 0.0) or 0.0)
    mark = float(levels.get("mark", 0.0) or 0.0)
    last = float(levels.get("last", 0.0) or 0.0)

    if bid > 0 and ask > 0 and ask >= bid:
        # Price inside spread but close to bid for quick execution.
        target = bid + (0.25 * (ask - bid))
    elif bid > 0:
        target = bid
    elif mark > 0:
        target = mark * 0.995
    elif last > 0:
        target = last * 0.995
    else:
        target = float(fallback_price or 0.0) * 0.995

    normalized = normalize_option_tick(float(target)) if target and target > 0 else 0.0
    if normalized <= 0:
        normalized = normalize_option_tick(float(fallback_price or 0.0)) if fallback_price else 0.0
    return normalized


def _compute_fast_entry_limit_price(option_symbol, fallback_mark):
    """Compute an aggressive buy-to-open limit price to reduce missed moves."""
    levels = _fetch_option_quote_snapshot(option_symbol)
    bid = float(levels.get("bid", 0.0) or 0.0)
    ask = float(levels.get("ask", 0.0) or 0.0)
    mark = float(levels.get("mark", 0.0) or 0.0)
    last = float(levels.get("last", 0.0) or 0.0)

    if ask > 0:
        target = ask
    elif mark > 0:
        target = mark * 1.005
    elif last > 0:
        target = last * 1.01
    elif fallback_mark and float(fallback_mark) > 0:
        target = float(fallback_mark) * 1.01
    elif bid > 0:
        target = bid
    else:
        target = 0.0

    normalized = normalize_option_tick(float(target)) if target and target > 0 else 0.0
    return normalized, levels


def _validate_entry_quote_snapshot(quote_snapshot):
    """Compatibility forwarder for the Brain-owned quote-admission decision."""
    decision = LIVE_BRAIN.evaluate_entry_quote(
        quote_snapshot,
        max_age_seconds=OPTION_QUOTE_MAX_STALE_SECONDS_OPEN,
        max_spread_pct=OPTION_QUOTE_MAX_SPREAD_PCT_OPEN,
    )
    return decision.allowed, decision.reason


def _wait_for_fill(order_id, option_symbol, limit_price, max_wait_seconds=ORDER_SUBMISSION_TIMEOUT_SECONDS):
    """
    Poll Schwab API waiting for order fill.
    
    Args:
        order_id: Schwab order ID
        option_symbol: Option symbol for logging
        limit_price: Submitted limit price
        max_wait_seconds: Maximum time to wait (default 30 seconds)
    
    Returns:
        (filled, fill_price) tuple:
            (True, price) if filled
            (False, None) if not filled after timeout
            (False, None) if rejected/cancelled
    """
    if not _schwab_client or not order_id:
        print("ERROR: Cannot check fill without client and order ID")
        return False, None
    
    start_time = time.time()
    check_interval = ORDER_CHECK_INTERVAL_SECONDS
    
    print(f"⏳ Waiting for fill (max {max_wait_seconds}s)...")
    
    while time.time() - start_time < max_wait_seconds:
        try:
            resp = _schwab_client.get_order(order_id, _schwab_account_hash)
            resp.raise_for_status()
            order_data = resp.json()
            
            status = order_data.get("status", "").upper()
            print(f"  Order status: {status}")
            
            if status == "FILLED":
                # Always anchor to actual broker execution legs when present.
                fill_price = _extract_execution_price(order_data)

                if fill_price is None:
                    # If broker marks FILLED but omits execution legs/price, fall back to
                    # submitted limit for continuity and reconciliation safety.
                    fill_price = float(limit_price or 0.0)
                    if fill_price <= 0:
                        print("ERROR: FILLED order returned no execution price")
                        return False, None
                
                print(f"✓ ORDER FILLED: {option_symbol} at {fill_price}")
                return True, fill_price
            
            elif status in ["REJECTED", "CANCELLED", "EXPIRED"]:
                print(f"✗ ORDER {status}: {option_symbol}")
                return False, None
            
            elif status == "PENDING_ACTIVATION":
                print(f"  ⏳ Pending activation...")
            
            # Still waiting
            time.sleep(check_interval)
            
        except Exception as e:
            print(f"ERROR checking fill: {e}")
            # Continue trying
            time.sleep(check_interval)
    
    # TIMEOUT: Order didn't fill via polling. Check positions to confirm.
    print(f"\n⏳ ORDER POLLING TIMEOUT after {max_wait_seconds}s")
    print(f"   Checking Schwab positions to detect fill...")
    
    try:
        positions, orders, status_code, error_text = get_schwab_positions()
        
        if positions is not None:
            # Check if the option position now exists on Schwab
            for pos in positions:
                if pos.get("instrument", {}).get("assetType") == "OPTION":
                    symbol = pos.get("instrument", {}).get("symbol", "")
                    if option_symbol in symbol or symbol in option_symbol:
                        qty = pos.get("longQuantity", 0)
                        if qty > 0:
                            print(f"✓ POSITION DETECTED on Schwab: {symbol} qty {qty}")
                            print(f"   Order filled but polling failed. Adopting broker position.")
                            # Return success - order filled even though polling failed
                            return True, pos.get("averagePrice", 0)
    except Exception as e:
        print(f"WARNING: Error reconciling positions: {e}")

    # If still not filled, proactively cancel working order so it cannot fill later
    # outside bot control (which would leave a position without automated protection).
    try:
        latest = _schwab_client.get_order(order_id, _schwab_account_hash)
        latest.raise_for_status()
        latest_data = latest.json() or {}
        latest_status = str(latest_data.get("status") or "").upper()
        active_statuses = {
            "PENDING_ACTIVATION",
            "ACCEPTED",
            "QUEUED",
            "WORKING",
            "PENDING_REPLACEMENT",
            "PARTIALLY_FILLED",
            "AWAITING_PARENT_ORDER",
            "AWAITING_CONDITION",
        }

        if latest_status in active_statuses:
            print(f"   Canceling timed-out entry order {order_id} (status {latest_status}) to prevent orphan fills")
            cancel_resp = _schwab_client.cancel_order(order_id, _schwab_account_hash)
            cancel_resp.raise_for_status()
            time.sleep(max(ORDER_CHECK_INTERVAL_SECONDS, 0.15))

            # One final reconciliation in case a fill raced our cancel.
            positions, _, _, _ = get_schwab_positions()
            if positions is not None:
                for pos in positions:
                    if pos.get("instrument", {}).get("assetType") != "OPTION":
                        continue
                    symbol = pos.get("instrument", {}).get("symbol", "")
                    qty = float(pos.get("longQuantity", 0) or 0)
                    if qty > 0 and (option_symbol in symbol or symbol in option_symbol):
                        print(f"✓ POSITION DETECTED after timeout/cancel race: {symbol} qty {qty}")
                        print("   Treating as filled so protective stop can still be placed.")
                        return True, pos.get("averagePrice", 0)
    except Exception as e:
        print(f"WARNING: Timed-out entry cancel/reconcile failed: {e}")
    
    print(f"✗ ORDER TIMEOUT: Did not fill within {max_wait_seconds} seconds")
    print(f"   No position found on Schwab")
    return False, None


def open_trade(direction, price, stop, target, quantity, reason, option=None, feature_payload=None):
    """
    Open a live trade on Schwab with ACTUAL order submission.
    
    Process:
    1. Check for existing entries and locks
    2. Check Schwab for existing SPY option exposure
    3. Submit order to Schwab
    4. Set ENTRY_PENDING lock
    5. Wait for fill confirmation
    6. Only create local position after confirmed fill
    7. Return False if order rejected/not filled
    
    Returns:
        True if order was filled and position created
        False if order failed/rejected/not filled
    """
    global current_position, _submission_rejected, _entry_pending, _pending_order_id, _max_quantity_exceeded
    global _safe_mode, _safe_mode_reason, _protective_stop_failed, _protective_stop_failure_reason

    open_trade_start_ms = _perf_ms_now()
    metrics = {
        "attempted": True,
        "opened": False,
        "block_reason": None,
        "precheck_ms": None,
        "quote_compute_ms": None,
        "submit_order_ms": None,
        "wait_fill_ms": None,
        "market_fallback_submit_ms": None,
        "market_fallback_wait_ms": None,
        "protective_stop_ms": None,
        "persist_ms": None,
        "total_open_trade_ms": None,
        "filled_via": None,
    }

    def _finalize(opened, block_reason=None):
        metrics["opened"] = bool(opened)
        metrics["block_reason"] = block_reason
        metrics["total_open_trade_ms"] = _elapsed_ms(open_trade_start_ms)
        _set_last_open_trade_metrics(metrics)
        return bool(opened)

    precheck_start_ms = _perf_ms_now()

    runtime_guard = LIVE_BRAIN.evaluate_entry_runtime_guard(
        quantity=quantity,
        required_quantity=MAX_OPEN_CONTRACTS,
        safe_mode=_safe_mode,
        submission_rejected=_submission_rejected,
        max_quantity_exceeded=_max_quantity_exceeded,
        protective_stop_failed=_protective_stop_failed,
        entry_pending=_entry_pending,
        already_in_trade=in_trade(),
    )
    if not runtime_guard.allowed:
        print(f"Trade blocked: {runtime_guard.reason}")
        metrics["precheck_ms"] = _elapsed_ms(precheck_start_ms)
        return _finalize(False, runtime_guard.reason)

    quantity = int(quantity)

    # CHECK SCHWAB FOR EXISTING SPY OPTION EXPOSURE (prevent duplicates)
    has_exposure, exposure_details = check_spy_option_exposure()
    allowed, block_reason = can_open_trade()
    entry_admission = LIVE_BRAIN.evaluate_entry_admission(
        has_broker_exposure=has_exposure,
        risk_allowed=allowed,
        risk_block_reason=block_reason,
        has_option_symbol=bool(option and option.get("symbol")),
    )
    if not entry_admission.allowed:
        print(f"Trade blocked: {entry_admission.reason}")
        metrics["precheck_ms"] = _elapsed_ms(precheck_start_ms)
        return _finalize(False, entry_admission.reason)

    metrics["precheck_ms"] = _elapsed_ms(precheck_start_ms)

    option_symbol = option.get("symbol")
    option_mark = float(option.get("mark", 0.0))

    quote_compute_start_ms = _perf_ms_now()
    limit_price, quote_levels = _compute_fast_entry_limit_price(option_symbol, option_mark)
    metrics["quote_compute_ms"] = _elapsed_ms(quote_compute_start_ms)
    quote_ok, quote_block_reason = _validate_entry_quote_snapshot(quote_levels)

    print(f"\n{'='*70}")
    print(f"🔴 LIVE TRADE ENTRY: {direction}")
    print(f"{'='*70}")
    print(f"Entry: {price} (SPY)")
    print(f"Stop: {stop}")
    print(f"Target: {target}")
    print(f"Option: {option_symbol}")
    print(
        f"Option Quote Levels: bid={quote_levels.get('bid')} ask={quote_levels.get('ask')} "
        f"mark={quote_levels.get('mark')} last={quote_levels.get('last')}"
    )
    if quote_levels.get("quote_age_seconds") is not None:
        print(
            f"Quote Freshness: age={float(quote_levels.get('quote_age_seconds') or 0.0):.1f}s "
            f"spread={quote_levels.get('quote_spread_pct') or '-'}% as_of={quote_levels.get('quote_as_of') or 'unknown'}"
        )
    print(f"Option Mark: {option_mark:.2f} → Entry Limit: {limit_price:.2f}")
    print(f"Quantity: {quantity}")

    if not quote_ok:
        print(f"\n🔒 ENTRY BLOCKED: option quote is not fresh enough to trust")
        print(f"   Reason: {quote_block_reason}")
        print("   No order submitted; bot remains flat")
        return _finalize(False, f"quote_guard:{quote_block_reason}")

    # STEP 1: Submit order to Schwab
    print("\n[STEP 1] Submitting order to Schwab...")
    submit_start_ms = _perf_ms_now()
    order_id = _submit_option_order(option_symbol, direction, limit_price, quantity)
    metrics["submit_order_ms"] = _elapsed_ms(submit_start_ms)

    if not order_id:
        print("✗ FAILED: Order not submitted to Schwab")
        print("✓ No position created (kept bot flat)")
        return _finalize(False, "submit_order_failed")

    # SET ENTRY_PENDING LOCK (prevent duplicate entries while fill is pending)
    _entry_pending = True
    _pending_order_id = order_id
    print(f"\n🔒 ENTRY_PENDING LOCK ACTIVATED (Order: {order_id})")
    print(f"   Blocking all additional entries until fill confirmed or timeout")

    # STEP 2: Wait for fill confirmation
    print("\n[STEP 2] Waiting for fill confirmation...")
    wait_start_ms = _perf_ms_now()
    filled, fill_price = _wait_for_fill(
        order_id,
        option_symbol,
        limit_price,
        max_wait_seconds=max(1.0, float(ENTRY_LIMIT_MAX_WAIT_SECONDS or 4.0)),
    )
    metrics["wait_fill_ms"] = _elapsed_ms(wait_start_ms)

    if filled:
        metrics["filled_via"] = "limit"

    if not filled:
        if ENTRY_MARKET_FALLBACK_ENABLED:
            print("⚠ LIMIT ENTRY MISSED: attempting market fallback for fast participation...")
            fallback_submit_start_ms = _perf_ms_now()
            market_order_id = _submit_option_entry_market_order(option_symbol, quantity)
            metrics["market_fallback_submit_ms"] = _elapsed_ms(fallback_submit_start_ms)
            if market_order_id:
                _pending_order_id = market_order_id
                fallback_wait_start_ms = _perf_ms_now()
                filled, fill_price = _wait_for_fill(
                    market_order_id,
                    option_symbol,
                    limit_price,
                    max_wait_seconds=max(1.0, float(ENTRY_MARKET_FALLBACK_MAX_WAIT_SECONDS or 4.0)),
                )
                metrics["market_fallback_wait_ms"] = _elapsed_ms(fallback_wait_start_ms)
                if filled:
                    metrics["filled_via"] = "market_fallback"

        if not filled:
            print("✗ FAILED: Entry did not fill after limit + market fallback")
            print("✓ No position created (kept bot flat)")
            # Clear entry pending lock - next attempt can try again
            _entry_pending = False
            _pending_order_id = None
            return _finalize(False, "entry_not_filled_after_limit_and_fallback")

    if fill_price is None or float(fill_price) <= 0:
        print("✗ FAILED: Filled order missing valid broker execution price")
        _entry_pending = False
        _pending_order_id = None
        return _finalize(False, "filled_without_valid_price")

    # STEP 3: Only NOW create the position after fill confirmation
    print("\n[STEP 3] Creating position in system...")

    fill_timestamp = datetime.now().isoformat()

    # STEP 4: Submit protective stop immediately after entry fill confirmed
    print("\n[STEP 4] Submitting broker-held protective stop...")
    protective_stop_start_ms = _perf_ms_now()
    protective_stop_id, protective_stop_price = _submit_protective_stop(option_symbol, float(fill_price), quantity)
    metrics["protective_stop_ms"] = _elapsed_ms(protective_stop_start_ms)

    if not protective_stop_id:
        print("\n❌ PROTECTIVE STOP SUBMISSION FAILED - POSITION UNPROTECTED")
        print("   The entry filled but protective stop was rejected")
        print("   EMERGENCY: Attempting immediate market close to avoid unprotected exposure")

        emergency_exit_id = _submit_option_exit_market_order(option_symbol, int(quantity or 0))
        if emergency_exit_id:
            emergency_filled, _ = _wait_for_fill(
                emergency_exit_id,
                option_symbol,
                float(fill_price or 0.0),
                max_wait_seconds=ORDER_SUBMISSION_TIMEOUT_SECONDS,
            )
            if emergency_filled:
                print("   ✓ Emergency close filled; position not left unprotected")
                _protective_stop_failed = False
                _protective_stop_failure_reason = None
                _entry_pending = False
                _pending_order_id = None
                return _finalize(False, "protective_stop_failed_emergency_close_filled")

        print("   Manual action required to protect/close this position")
        # Activate protective stop failure lock
        _protective_stop_failed = True
        _protective_stop_failure_reason = "Stop submission failed after entry fill; emergency close failed"
        # Still save the position but mark stop as failed
        protective_stop_id = ""
        protective_stop_price = 0.0
    else:
        print(f"\n✓ Position protection established")

    current_position = Position(
        direction=direction,
        entry_price=price,
        stop_price=stop,
        target_price=target,
        quantity=quantity,
        opened=datetime.now(),
        reason=reason,
        option_symbol=option_symbol,
        option_entry=float(fill_price),
        option_delta=option.get("delta", 0.0),
        feature_payload=feature_payload or "",
        schwab_order_id=order_id,
        schwab_fill_price=float(fill_price),
        schwab_fill_timestamp=fill_timestamp,
        submitted_limit_price=limit_price,
        protective_stop_order_id=protective_stop_id,
        protective_stop_price=protective_stop_price,
        protective_stop_status="PLACED" if protective_stop_id else "FAILED",
    )

    persist_start_ms = _perf_ms_now()
    try:
        save_position(current_position)
        metrics["persist_ms"] = _elapsed_ms(persist_start_ms)
        print(f"✓ Position saved to disk (Order ID: {order_id})")
    except Exception as exc:
        metrics["persist_ms"] = _elapsed_ms(persist_start_ms)
        print(f"ERROR: position file save failed: {exc}")
        print("✗ Position not persisted - trade is NOT in recovery list")
        # Clear entry pending lock before returning
        _entry_pending = False
        _pending_order_id = None
        return _finalize(False, "position_persist_failed")

    try:
        _record_entry_feature_vector(feature_payload, order_id)
    except Exception as exc:
        print(f"WARNING: Could not persist entry feature vector: {exc}")

    print(f"\n✓✓✓ TRADE OPENED SUCCESSFULLY ✓✓✓")
    print(f"  Order ID: {order_id}")
    print(f"  Fill Price: {float(fill_price):.2f}")
    print(f"  Timestamp: {fill_timestamp}")
    print(f"{'='*70}\n")

    # Clear entry pending lock (fill confirmed)
    _entry_pending = False
    _pending_order_id = None

    send_trade_entry_alert(
        mode="LIVE",
        direction=direction,
        quantity=int(quantity or 0),
        option_symbol=option_symbol,
        option_entry=float(fill_price or 0.0),
        spy_entry=float(price or 0.0),
        reason=reason,
    )

    try:
        log_trade_diagnostic_event(
            event_type="ENTRY",
            direction=direction,
            option_symbol=option_symbol,
            source="LIVE",
            snapshot=_extract_entry_diagnostic_snapshot(feature_payload or "") or (feature_payload or ""),
        )
    except Exception as e:
        print(f"WARNING: Could not persist live ENTRY diagnostic snapshot: {e}")

    return _finalize(True, None)


def close_trade(price, reason, option_mark=None, execution_mode="market", limit_price=None, fallback_to_market=True):
    """
    Close a live trade on Schwab.
    
    CRITICAL SEQUENCE:
    1. Cancel broker-held protective stop
    2. Submit closing order  
    3. Confirm close on Schwab
    4. Clear local position
    5. Log the trade (failure won't prevent closure)
    """
    global current_position, _protective_stop_failed, _protective_stop_failure_reason

    if not current_position:
        return False

    # Save position data before clearing (for logging and stop cancellation)
    saved_position = current_position
    
    # STEP 1: Cancel protective stop before submitting exit
    if saved_position.protective_stop_order_id:
        print(f"\n[STEP 1] Canceling broker-held protective stop...")
        cancel_success = _cancel_protective_stop(saved_position.protective_stop_order_id)
        if not cancel_success:
            print(f"WARNING: Could not confirm protective stop cancellation, continuing with exit")
    else:
        print(f"[STEP 1] No protective stop to cancel")
    
    # STEP 2: Submit actual exit order to Schwab and confirm fill.
    exit_order_id = None
    if saved_position.option_symbol and int(saved_position.quantity or 0) > 0:
        use_limit_mode = str(execution_mode or "market").lower() == "limit_near_market"
        if use_limit_mode:
            if limit_price is None:
                limit_price = _compute_fast_exit_limit_price(saved_position.option_symbol, option_mark or saved_position.option_entry)
            print(f"[STEP 2] Submitting SELL_TO_CLOSE limit exit near market @ ${float(limit_price or 0):.2f}...")
            exit_order_id = _submit_option_exit_limit_order(
                saved_position.option_symbol,
                int(saved_position.quantity or 0),
                float(limit_price or 0.0),
            )
        else:
            print(f"[STEP 2] Submitting SELL_TO_CLOSE market exit...")
            exit_order_id = _submit_option_exit_market_order(
                saved_position.option_symbol,
                int(saved_position.quantity or 0),
            )

        if not exit_order_id:
            if use_limit_mode and fallback_to_market:
                print("WARNING: Limit exit submission failed, falling back to market exit")
                exit_order_id = _submit_option_exit_market_order(
                    saved_position.option_symbol,
                    int(saved_position.quantity or 0),
                )

        if not exit_order_id:
            print("❌ EXIT SUBMISSION FAILED: keeping position open for retry/reconciliation")
            # Best-effort re-protect if we canceled the original protective stop.
            if saved_position.option_stop and saved_position.option_stop > 0:
                _submit_protective_stop(
                    saved_position.option_symbol,
                    float(saved_position.option_entry or 0.0),
                    int(saved_position.quantity or 0),
                    stop_price_override=float(saved_position.option_stop),
                )
            return False

        filled, exit_fill = _wait_for_fill(
            exit_order_id,
            saved_position.option_symbol,
            float(limit_price or option_mark or 0.0),
            max_wait_seconds=12 if use_limit_mode else ORDER_SUBMISSION_TIMEOUT_SECONDS,
        )
        if not filled:
            if use_limit_mode and fallback_to_market:
                print("WARNING: Limit exit not filled quickly, falling back to market exit")
                market_exit_id = _submit_option_exit_market_order(
                    saved_position.option_symbol,
                    int(saved_position.quantity or 0),
                )
                if market_exit_id:
                    filled, exit_fill = _wait_for_fill(
                        market_exit_id,
                        saved_position.option_symbol,
                        float(option_mark or 0.0),
                        max_wait_seconds=ORDER_SUBMISSION_TIMEOUT_SECONDS,
                    )
                    exit_order_id = market_exit_id if filled else exit_order_id

        if not filled:
            print("❌ EXIT FILL FAILED/TIMEOUT: keeping position open for retry/reconciliation")
            if saved_position.option_stop and saved_position.option_stop > 0:
                _submit_protective_stop(
                    saved_position.option_symbol,
                    float(saved_position.option_entry or 0.0),
                    int(saved_position.quantity or 0),
                    stop_price_override=float(saved_position.option_stop),
                )
            return False

        if exit_fill is not None:
            try:
                option_mark = float(exit_fill)
            except (TypeError, ValueError):
                pass
    
    if current_position.direction == "CALL":
        pnl = price - current_position.entry_price
    else:
        pnl = current_position.entry_price - price

    trade_log.append({
        "entry": current_position.entry_price,
        "exit": price,
        "direction": current_position.direction,
        "pnl": pnl,
        "reason": reason,
        "opened": current_position.opened,
        "closed": datetime.now(),
        "mode": "LIVE",  # Mark as live trade
        "schwab_order_id": current_position.schwab_order_id,
    })

    option_entry_price = float(current_position.option_entry or 0)
    option_exit_price = float(option_mark or 0)
    reason = _guard_exit_reason(reason, option_entry_price, option_exit_price)
    momentum_freshness_score, momentum_phase = _extract_momentum_fields(getattr(saved_position, "feature_payload", ""))
    entry_diagnostic_snapshot = _extract_entry_diagnostic_snapshot(getattr(saved_position, "feature_payload", ""))
    absorption_score = _extract_absorption_score(getattr(saved_position, "feature_payload", ""), saved_position.direction)
    exit_diagnostic_snapshot = _build_exit_diagnostic_snapshot(
        direction=saved_position.direction,
        reason=reason,
        source="LIVE_CLOSE",
        underlying_entry=saved_position.entry_price,
        underlying_exit=price,
        option_entry=option_entry_price,
        option_exit=option_exit_price,
    )
    
    option_return = None
    option_pnl_dollars = None
    option_pnl_pct = None
    
    if option_entry_price > 0 and option_exit_price > 0:
        option_return = (
            (option_exit_price - option_entry_price)
            / option_entry_price
            * 100
        )
        option_pnl_dollars = (
            (option_exit_price - option_entry_price)
            * current_position.quantity
            * 100  # Assuming 100 multiplier for options
        )
        option_pnl_pct = (
            (option_exit_price - option_entry_price)
            / option_entry_price
        )

    # Record trade exit first (before logging)
    record_trade(pnl)
    print(f"🔴 LIVE CLOSE {reason}")  # Live mode indicator
    print(f"Exit: {price}")
    print(f"P&L: {pnl:.2f}")
    print(f"[LIVE MODE] Order closed on Schwab account")

    # Clear position from memory and disk BEFORE logging
    try:
        clear_position()
    except Exception as exc:
        print(f"WARNING: position file clear failed: {exc}")

    current_position = None
    # Clearing position resets alarm lock so new entries can resume while flat.
    _protective_stop_failed = False
    _protective_stop_failure_reason = None
    
    # NOW attempt logging (failure won't affect position closure)
    try:
        try:
            log_trade_diagnostic_event(
                event_type="EXIT",
                direction=saved_position.direction,
                option_symbol=saved_position.option_symbol,
                source="LIVE",
                snapshot=exit_diagnostic_snapshot,
            )
        except Exception as e:
            print(f"WARNING: Could not persist live EXIT diagnostic snapshot: {e}")

        safe_log_trade(
            entry_time=saved_position.opened.isoformat(),
            exit_time=datetime.now().isoformat(),
            direction=saved_position.direction,
            entry_price=saved_position.entry_price,
            exit_price=price,
            pnl=pnl,
            exit_reason=reason,
            feature_payload=saved_position.feature_payload,
            option_symbol=saved_position.option_symbol,
            option_entry=option_entry_price,
            option_exit=option_exit_price,
            option_quantity=saved_position.quantity,
            option_delta=saved_position.option_delta,
            option_return=option_return,
            option_pnl_dollars=option_pnl_dollars,
            option_pnl_pct=option_pnl_pct,
            broker_entry_order_id=str(saved_position.schwab_order_id or "") or None,
            broker_exit_order_id=str(exit_order_id or "") or None,
            momentum_freshness_score=momentum_freshness_score,
            momentum_phase=momentum_phase,
            absorption_score=absorption_score,
            entry_diagnostic_snapshot=entry_diagnostic_snapshot,
            exit_diagnostic_snapshot=exit_diagnostic_snapshot,
        )
    except Exception as log_exc:
        print(f"\n⚠️  LOGGING ERROR (position already closed): {log_exc}")
        print(f"Position is CLOSED - logging failure does not affect trade")
        import traceback
        print("Traceback:")
        traceback.print_exc()
        # Continue - position is already closed, don't re-throw

    send_trade_exit_alert(
        mode="LIVE",
        direction=saved_position.direction,
        quantity=int(saved_position.quantity or 0),
        option_symbol=saved_position.option_symbol or "",
        option_entry=float(option_entry_price or 0.0),
        option_exit=float(option_exit_price or 0.0),
        pnl_dollars=float(option_pnl_dollars or 0.0),
        pnl_pct=float((option_pnl_pct or 0.0) * 100.0),
        exit_reason=reason,
    )
    
    return True


def manage_trade(current_price, option_mark=None, option_bid=None):
    """Execute the canonical Brain management decision against Schwab."""
    global current_position, _protective_stop_failed, _protective_stop_failure_reason

    if not in_trade():
        return
    _sync_position_with_broker(current_price)
    if not in_trade():
        return

    global _last_protective_stop_check_epoch, _last_protective_stop_check_ok
    now_epoch = time.time()
    should_check_stop = (
        (now_epoch - float(_last_protective_stop_check_epoch or 0.0))
        >= max(0.25, float(PROTECTIVE_STOP_CHECK_MIN_INTERVAL_SECONDS or 3.0))
        or not bool(_last_protective_stop_check_ok)
    )
    if should_check_stop and current_position.option_symbol:
        protective_stop_active = _has_active_protective_stop_order(current_position.option_symbol)
        _last_protective_stop_check_epoch = now_epoch
        _last_protective_stop_check_ok = bool(protective_stop_active)
    else:
        protective_stop_active = bool(_last_protective_stop_check_ok)

    decision = LIVE_BRAIN.manage_trade(
        current_position,
        {
            "current_price": current_price,
            "option_mark": option_mark,
            "option_bid": option_bid,
            "protective_stop_active": protective_stop_active,
            "now": datetime.now(),
        },
    )
    for field_name, value in decision.metadata.get("state_updates", {}).items():
        setattr(current_position, field_name, value)

    if decision.action is TradeAction.RESTORE_PROTECTIVE_STOP:
        _send_unprotected_position_alert(current_position.option_symbol, decision.quantity, decision.stop_price)
        order_id, submitted_stop = _submit_protective_stop(
            current_position.option_symbol,
            float(current_position.option_entry or 0.0),
            int(decision.quantity or 0),
            stop_price_override=float(decision.stop_price or 0.0),
            existing_stop_order_id=current_position.protective_stop_order_id or None,
        )
        if not order_id:
            _protective_stop_failed = True
            _protective_stop_failure_reason = "Protective-stop verification/restore failed; manual broker verification required"
            protection_decision = LIVE_BRAIN.evaluate_protective_stop_result(
                current_position,
                restored=False,
                restore_count=int(current_position.protective_stop_restore_count or 0),
            )
            close_trade(current_price, protection_decision.reason, option_mark)
            return
        current_position.protective_stop_order_id = str(order_id)
        current_position.protective_stop_price = float(submitted_stop or decision.stop_price or 0.0)
        current_position.protective_stop_status = "PLACED"
        current_position.protective_stop_restore_count = int(current_position.protective_stop_restore_count or 0) + 1
        _last_protective_stop_check_ok = True
        _last_protective_stop_check_epoch = time.time()
        protection_decision = LIVE_BRAIN.evaluate_protective_stop_result(
            current_position,
            restored=True,
            restore_count=current_position.protective_stop_restore_count,
        )
        if protection_decision.action is TradeAction.BLOCK_NEW_ENTRIES:
            _protective_stop_failed = True
            _protective_stop_failure_reason = protection_decision.reason
        save_position(current_position)
        return

    if decision.action is TradeAction.UPDATE_STOP:
        order_id, submitted_stop = _submit_protective_stop(
            current_position.option_symbol,
            float(current_position.option_entry or 0.0),
            int(decision.quantity or 0),
            stop_price_override=float(decision.stop_price or 0.0),
            existing_stop_order_id=current_position.protective_stop_order_id or None,
        )
        if not order_id:
            _protective_stop_failed = True
            _protective_stop_failure_reason = "Ratcheted protective-stop sync failed; manual broker verification required"
            protection_decision = LIVE_BRAIN.evaluate_protective_stop_result(
                current_position,
                restored=False,
                restore_count=int(current_position.protective_stop_restore_count or 0),
            )
            close_trade(current_price, protection_decision.reason, option_mark)
            return
        current_position.protective_stop_order_id = str(order_id)
        current_position.protective_stop_price = float(submitted_stop or decision.stop_price or 0.0)
        current_position.protective_stop_status = "PLACED"
        save_position(current_position)
        return

    if decision.action is TradeAction.EXIT:
        close_trade(current_price, decision.reason, decision.metadata.get("exit_option_mark"))
        return

    if decision.metadata.get("state_updates"):
        save_position(current_position)
