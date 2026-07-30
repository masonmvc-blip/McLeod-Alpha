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
from execution.entry_quote_telemetry import attach_entry_quote_telemetry
from execution.contract_limits import MAX_OPEN_CONTRACTS
from execution.diagnostic_snapshots import extract_entry_diagnostic_snapshot
from execution.stop_telemetry import record_stop_event
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as dt_time, timezone
from zoneinfo import ZoneInfo
from engine.brain import Brain, TradeAction, can_open_trade, record_trade, record_stop
from engine.memory import get_memory
from execution.trade_logger import log_trade, log_bot_order, log_trade_diagnostic_event
from execution.exit_quality import exit_quality_metrics, update_option_extrema
from execution.option_quote_telemetry import record_option_management_cycle
import os
import time
import json
import sqlite3
import threading
import subprocess
from pathlib import Path

EASTERN_TZ = ZoneInfo("America/New_York")
ENTRY_CUTOFF_TIME = dt_time(15, 45)
NATIVE_AUDIO_PLAYER = Path("/usr/bin/afplay")
EXECUTION_AUDIO_PATHS = {
    "entry": Path(__file__).resolve().parents[1] / "static" / "audio" / "trade_kaching.mp3",
    "profit_exit": Path(__file__).resolve().parents[1] / "static" / "audio" / "trade_kaching.mp3",
    "loss_exit": Path(__file__).resolve().parents[1] / "static" / "audio" / "trade_loss_trumpet.mp3",
}
EXECUTION_AUDIO_STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "execution_audio_alerts.json"
_execution_audio_lock = threading.Lock()

# Global Schwab client and account configuration
# Set by phase3_monitor.py after client creation
_schwab_client = None
_schwab_account_number = None
_schwab_account_hash = None
_last_broker_sync_epoch = 0.0
BROKER_SYNC_MIN_INTERVAL_SECONDS = float(os.getenv("BROKER_SYNC_MIN_INTERVAL_SECONDS", "2.0"))
PROTECTIVE_STOP_CHECK_MIN_INTERVAL_SECONDS = float(os.getenv("PROTECTIVE_STOP_CHECK_MIN_INTERVAL_SECONDS", "5.0"))
_last_protective_stop_check_epoch = 0.0
_last_protective_stop_check_ok = True
_last_protective_stop_submission_epoch = 0.0
BROKER_RECONCILE_MAX_ATTEMPTS = max(1, int(os.getenv("BROKER_RECONCILE_MAX_ATTEMPTS", "3")))
BROKER_RECONCILE_RETRY_DELAY_SECONDS = max(1.0, float(os.getenv("BROKER_RECONCILE_RETRY_DELAY_SECONDS", "6")))
OPTION_QUOTE_MAX_STALE_SECONDS_OPEN = max(1.0, float(os.getenv("OPTION_QUOTE_MAX_STALE_SECONDS_OPEN", "8")))
OPTION_QUOTE_MAX_SPREAD_PCT_OPEN = max(0.0, float(os.getenv("OPTION_QUOTE_MAX_SPREAD_PCT_OPEN", "15")))
STOP_RATCHET_MAX_QUOTE_AGE_SECONDS = max(0.5, float(os.getenv("STOP_RATCHET_MAX_QUOTE_AGE_SECONDS", "3")))
STOP_RATCHET_MAX_SPREAD_PCT = max(0.0, float(os.getenv("STOP_RATCHET_MAX_SPREAD_PCT", "12")))
STOP_RATCHET_MIN_INTERVAL_SECONDS = max(1.0, float(os.getenv("STOP_RATCHET_MIN_INTERVAL_SECONDS", "2")))
STOP_RATCHET_MIN_IMPROVEMENT_DOLLARS = max(0.01, float(os.getenv("STOP_RATCHET_MIN_IMPROVEMENT_DOLLARS", "0.03")))
STOP_RATCHET_MARKET_BUFFER_DOLLARS = max(
    0.01,
    float(os.getenv("STOP_RATCHET_MARKET_BUFFER_DOLLARS", "0.02")),
)
BROKER_REQUEST_MIN_INTERVAL_SECONDS = max(0.0, float(os.getenv("BROKER_REQUEST_MIN_INTERVAL_SECONDS", "0.75")))
BROKER_RATE_LIMIT_FALLBACK_SECONDS = max(1.0, float(os.getenv("BROKER_RATE_LIMIT_FALLBACK_SECONDS", "30")))
BROKER_RATE_LIMIT_STATE_FILE = Path(__file__).resolve().parents[1] / "data" / "broker_rate_limit.json"
BROKER_RECONCILIATION_SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "data" / "broker_reconciliation_snapshot.json"
POST_EXIT_COOLING_FILE = Path(__file__).resolve().parents[1] / "data" / "post_exit_cooling.json"
_broker_request_lock = threading.Lock()
_last_broker_request_epoch = 0.0
_broker_rate_limited_until_epoch = 0.0


def _load_broker_rate_limit_cooldown():
    """Restore a broker-directed cooldown after a bot restart."""
    try:
        payload = json.loads(BROKER_RATE_LIMIT_STATE_FILE.read_text())
        return float(payload.get("rate_limited_until_epoch") or 0.0)
    except (OSError, ValueError, TypeError):
        return 0.0


def _persist_broker_rate_limit_cooldown():
    try:
        BROKER_RATE_LIMIT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BROKER_RATE_LIMIT_STATE_FILE.write_text(json.dumps({
            "rate_limited_until_epoch": _broker_rate_limited_until_epoch,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }))
    except OSError as exc:
        print(f"WARNING: Could not persist Schwab rate-limit cooldown: {exc}")


def _persist_broker_reconciliation_snapshot(spy_positions, spy_orders):
    """Project only the broker facts needed for local position reconciliation."""
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "SUCCESS",
        "spy_option_positions": [
            {"symbol": str(symbol), "quantity": float(quantity)}
            for symbol, quantity, _position in spy_positions
        ],
        "spy_option_orders": [
            {"symbol": str(symbol), "quantity": float(quantity), "status": str(status)}
            for symbol, quantity, status, _order in spy_orders
        ],
    }
    try:
        BROKER_RECONCILIATION_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = BROKER_RECONCILIATION_SNAPSHOT_PATH.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(BROKER_RECONCILIATION_SNAPSHOT_PATH)
    except OSError as exc:
        print(f"WARNING: Could not persist broker reconciliation snapshot: {exc}")


def _claim_execution_audio_event(event_id: str | None) -> bool:
    """Atomically suppress retries of the same confirmed broker execution."""
    if not event_id:
        return True

    with _execution_audio_lock:
        try:
            payload = json.loads(EXECUTION_AUDIO_STATE_PATH.read_text(encoding="utf-8"))
            played_event_ids = list(payload.get("played_event_ids") or [])
        except (OSError, ValueError, TypeError):
            played_event_ids = []

        if event_id in played_event_ids:
            return False

        played_event_ids.append(event_id)
        try:
            EXECUTION_AUDIO_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temp_path = EXECUTION_AUDIO_STATE_PATH.with_suffix(".tmp")
            temp_path.write_text(
                json.dumps({"played_event_ids": played_event_ids[-200:]}, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(EXECUTION_AUDIO_STATE_PATH)
        except OSError as exc:
            print(f"WARNING: Could not persist execution audio state: {exc}")
        return True


def _play_execution_alert(
    event: str,
    pnl_dollars: float | None = None,
    *,
    event_id: str | None = None,
) -> None:
    """Play one local macOS alert per confirmed broker execution."""
    if event == "entry":
        alert_kind = "entry"
    elif pnl_dollars is not None and float(pnl_dollars) > 0:
        alert_kind = "profit_exit"
    elif pnl_dollars is not None and float(pnl_dollars) < 0:
        alert_kind = "loss_exit"
    else:
        return
    audio_path = EXECUTION_AUDIO_PATHS[alert_kind]
    try:
        if not NATIVE_AUDIO_PLAYER.is_file() or not audio_path.is_file():
            return
        if not _claim_execution_audio_event(event_id):
            return
        subprocess.Popen(
            [str(NATIVE_AUDIO_PLAYER), str(audio_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        print(f"WARNING: Could not play local {alert_kind} alert: {exc}")


def _arm_post_exit_cooling(
    exit_reason: str,
    source: str,
    exit_event_id: str | None = None,
) -> None:
    """Persist a restart-safe one-signal cooling block after a confirmed exit."""
    try:
        memory = get_memory()
        try:
            existing = memory.load_setting(POST_EXIT_COOLING_FILE, {}) or {}
        except Exception:
            existing = {}
        normalized_event_id = str(exit_event_id or "").strip() or None
        if (
            bool(existing.get("pending"))
            and normalized_event_id
            and str(existing.get("exit_event_id") or "") == normalized_event_id
        ):
            return
        memory.save_setting(
            "post_exit_cooling",
            {
                "schema_version": "post-exit-cooling.v2",
                "pending": True,
                "signals_remaining": 1,
                "exit_reason": str(exit_reason or ""),
                "exited_at": datetime.now(timezone.utc).isoformat(),
                "source": str(source or "live_engine"),
                "exit_event_id": normalized_event_id,
            },
            POST_EXIT_COOLING_FILE,
        )
        print("POST-EXIT COOLING: next qualifying entry signal will be skipped")
    except Exception as exc:
        print(f"WARNING: Could not persist post-exit cooling state: {exc}")


def _record_broker_rate_limit(response=None):
    """Honor Schwab Retry-After, or apply a conservative fallback cooldown."""
    global _broker_rate_limited_until_epoch
    retry_after = None
    headers = getattr(response, "headers", {}) or {}
    try:
        retry_after = float(headers.get("Retry-After") or headers.get("retry-after"))
    except (TypeError, ValueError):
        retry_after = None
    cooldown_seconds = max(1.0, retry_after or BROKER_RATE_LIMIT_FALLBACK_SECONDS)
    _broker_rate_limited_until_epoch = max(
        _broker_rate_limited_until_epoch,
        time.time() + cooldown_seconds,
    )
    _persist_broker_rate_limit_cooldown()
    print(f"[SCHWAB RATE LIMIT] Cooling down all broker requests for {cooldown_seconds:.0f}s")


class _GovernedBrokerResponse:
    """Response proxy that detects rate-limit errors at raise_for_status()."""

    def __init__(self, response):
        self._response = response

    def raise_for_status(self):
        try:
            return self._response.raise_for_status()
        except Exception:
            if getattr(self._response, "status_code", None) == 429:
                _record_broker_rate_limit(self._response)
            raise

    def __getattr__(self, name):
        return getattr(self._response, name)


class _GovernedSchwabClient:
    """Serialize Schwab API traffic and preserve capacity for order safety."""

    def __init__(self, client):
        self._client = client

    def __getattr__(self, name):
        attribute = getattr(self._client, name)
        if not callable(attribute) or isinstance(attribute, type):
            return attribute

        def governed_call(*args, **kwargs):
            global _last_broker_request_epoch
            with _broker_request_lock:
                now = time.time()
                if _broker_rate_limited_until_epoch > now:
                    wait_seconds = _broker_rate_limited_until_epoch - now
                    print(f"[SCHWAB RATE LIMIT] Blocking {name}; retry available in {wait_seconds:.0f}s")
                    raise RuntimeError(f"Schwab rate-limit cooldown active for {wait_seconds:.0f}s")
                spacing = BROKER_REQUEST_MIN_INTERVAL_SECONDS - (now - _last_broker_request_epoch)
                if spacing > 0:
                    time.sleep(spacing)
                try:
                    response = attribute(*args, **kwargs)
                except Exception as exc:
                    response = getattr(exc, "response", None)
                    if getattr(response, "status_code", None) == 429:
                        _record_broker_rate_limit(response)
                    raise
                _last_broker_request_epoch = time.time()
                return _GovernedBrokerResponse(response) if hasattr(response, "raise_for_status") else response

        return governed_call


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
    global _last_broker_request_epoch, _broker_rate_limited_until_epoch
    global LAST_OPEN_TRADE_METRICS
    
    _schwab_client = _GovernedSchwabClient(client)
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
    _last_protective_stop_submission_epoch = 0.0
    _last_broker_request_epoch = 0.0
    _broker_rate_limited_until_epoch = _load_broker_rate_limit_cooldown()
    LAST_OPEN_TRADE_METRICS = {
        "attempted": False,
        "opened": False,
        "block_reason": None,
        "precheck_ms": None,
        "quote_compute_ms": None,
        "submit_order_ms": None,
        "wait_fill_ms": None,
        "reprice_submit_ms": None,
        "reprice_wait_ms": None,
        "initial_limit_price": None,
        "final_limit_price": None,
        "entry_price_cap": None,
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


def preflight_entry_exposure():
    """Refresh broker exposure before the next closed-candle entry decision."""
    global _entry_exposure_preflight, _last_entry_exposure_preflight_epoch

    now_epoch = time.time()
    if (now_epoch - float(_last_entry_exposure_preflight_epoch or 0.0)) < ENTRY_EXPOSURE_PREFLIGHT_REFRESH_SECONDS:
        return _entry_exposure_preflight

    has_exposure, details = check_spy_option_exposure()
    _entry_exposure_preflight = (now_epoch, bool(has_exposure), details)
    _last_entry_exposure_preflight_epoch = now_epoch
    return _entry_exposure_preflight


def _fresh_entry_exposure_preflight():
    """Return a fresh pre-close broker result, or None when a live check is needed."""
    if not _entry_exposure_preflight:
        return None
    captured_epoch, has_exposure, details = _entry_exposure_preflight
    if (time.time() - float(captured_epoch or 0.0)) > ENTRY_EXPOSURE_PREFLIGHT_MAX_AGE_SECONDS:
        return None
    return bool(has_exposure), details


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
    terminal_order_statuses = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED", "REPLACED"}
    for order in orders:
        if str(order.get("status") or "").upper() not in terminal_order_statuses:
            legs = order.get("orderLegCollection", [])
            for leg in legs:
                instr = leg.get("instrument", {})
                if instr.get("assetType") == "OPTION":
                    symbol = instr.get("symbol", "")
                    if "SPY" in symbol:
                        qty = leg.get("quantity", 0)
                        status = order.get("status", "")
                        spy_orders.append((symbol, qty, status, order))

    _persist_broker_reconciliation_snapshot(spy_positions, spy_orders)
    
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
        if current_position is not None:
            print("[RECONCILIATION] Clearing stale local position; Schwab confirms no SPY exposure")
            clear_position()
            current_position = None
    
    print("="*70 + "\n")
    return True


# Configuration for order submission
ORDER_SUBMISSION_TIMEOUT_SECONDS = 30  # Wait up to 30 seconds for fill
ORDER_CHECK_INTERVAL_SECONDS = float(os.getenv("ORDER_CHECK_INTERVAL_SECONDS", "0.08"))  # Check fill status every 80ms
ORDER_QUANTITY = MAX_OPEN_CONTRACTS      # Target the configured maximum per trade
ENTRY_LIMIT_MAX_WAIT_SECONDS = float(os.getenv("ENTRY_LIMIT_MAX_WAIT_SECONDS", "0.35"))
ENTRY_REPRICE_MAX_WAIT_SECONDS = float(os.getenv("ENTRY_REPRICE_MAX_WAIT_SECONDS", "0.35"))
ENTRY_MAX_CHASE_DOLLARS = max(
    0.01,
    float(os.getenv("ENTRY_MAX_CHASE_DOLLARS", "0.05")),
)
# Market fallback is intentionally opt-in. A market order can consume most of
# a 6% scalp edge while the quote is moving; the normal fallback is now a
# refreshed, price-capped marketable limit.
ENTRY_MARKET_FALLBACK_MAX_WAIT_SECONDS = float(os.getenv("ENTRY_MARKET_FALLBACK_MAX_WAIT_SECONDS", "0.35"))
ENTRY_MARKET_FALLBACK_ENABLED = str(os.getenv("ENTRY_MARKET_FALLBACK_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}
ENTRY_OPTION_BUYING_POWER_RESERVE_DOLLARS = max(
    0.0,
    float(os.getenv("ENTRY_OPTION_BUYING_POWER_RESERVE_DOLLARS", "0")),
)
ENTRY_EXPOSURE_PREFLIGHT_MAX_AGE_SECONDS = max(1.0, float(os.getenv("ENTRY_EXPOSURE_PREFLIGHT_MAX_AGE_SECONDS", "5")))
ENTRY_EXPOSURE_PREFLIGHT_REFRESH_SECONDS = max(0.5, float(os.getenv("ENTRY_EXPOSURE_PREFLIGHT_REFRESH_SECONDS", "1.5")))
_entry_exposure_preflight = None
_last_entry_exposure_preflight_epoch = 0.0
_last_entry_order_status = None
_last_entry_order_status_description = None


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


def _max_affordable_option_contracts(
    available_funds,
    option_price,
    requested_quantity=MAX_OPEN_CONTRACTS,
    reserve_dollars=ENTRY_OPTION_BUYING_POWER_RESERVE_DOLLARS,
):
    """Return the largest whole-contract quantity Schwab funds can support."""
    try:
        available = max(0.0, float(available_funds))
        premium = float(option_price)
        requested = min(MAX_OPEN_CONTRACTS, max(0, int(requested_quantity)))
        reserve = max(0.0, float(reserve_dollars or 0.0))
    except (TypeError, ValueError):
        return 0

    contract_cost = premium * 100.0
    spendable = max(0.0, available - reserve)
    if contract_cost <= 0.0 or requested <= 0:
        return 0
    return min(requested, int(spendable // contract_cost))


def _get_available_option_buying_funds():
    """Fetch the balance Schwab applies to fully paid long-option purchases."""
    if not _schwab_client or not _schwab_account_hash:
        return None

    try:
        response = _schwab_client.get_account(_schwab_account_hash)
        response.raise_for_status()
        account = (response.json() or {}).get("securitiesAccount", {}) or {}
        current_balances = account.get("currentBalances", {}) or {}
        for field_name in ("availableFundsNonMarginableTrade", "availableFunds"):
            value = current_balances.get(field_name)
            if value is None:
                continue
            funds = float(value)
            if funds >= 0.0:
                return funds
    except Exception as exc:
        print(f"WARNING: Could not verify option buying funds: {exc}")
    return None


def _entry_terminal_block_reason(status, status_description=None):
    """Map a broker terminal status to an actionable entry block reason."""
    normalized_status = str(status or "").strip().upper()
    description = str(status_description or "").strip().lower()
    if normalized_status == "REJECTED" and (
        "buying power" in description or "available cash" in description
    ):
        return "insufficient_option_buying_power"
    if normalized_status == "REJECTED":
        return "entry_order_rejected"
    if normalized_status in {"CANCELLED", "CANCELED", "EXPIRED"}:
        return f"entry_order_{normalized_status.lower()}"
    return None


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
    protective_stop_price: float = 0.0  # Stop trigger price (initially 4% below fill)
    protective_stop_status: str = ""    # PENDING, PLACED, FAILED, CANCELED
    protective_stop_verification_requested_at: str = ""
    protective_stop_verification_kind: str = ""
    protective_stop_restore_count: int = 0  # Number of in-trade restore operations
    option_high_since_entry: float = 0.0
    option_low_since_entry: float = 0.0
    option_high_timestamp: str = ""
    option_low_timestamp: str = ""
    spy_price_at_option_high: float = 0.0
    spy_price_at_option_low: float = 0.0
    option_trailing_high_bid: float = 0.0  # Highest reliable executable bid used by the synthetic trail


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

# A rejected exit request must not become a high-frequency broker retry loop.
_last_exit_submission_failure_epoch = 0.0
EXIT_SUBMISSION_RETRY_COOLDOWN_SECONDS = 30

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
    "reprice_submit_ms": None,
    "reprice_wait_ms": None,
    "initial_limit_price": None,
    "final_limit_price": None,
    "entry_price_cap": None,
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
    """Return True, False, or None when broker verification is unavailable."""
    if not _schwab_client or not _schwab_account_hash or not option_symbol:
        return None

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

    # Prefer the exact order already attached to the position. Schwab's
    # account-order listing can lag immediately after an accepted replacement,
    # which previously made a working stop appear missing and caused an
    # identical replacement to be submitted.
    known_order_id = ""
    if current_position and current_position.option_symbol == option_symbol:
        known_order_id = str(current_position.protective_stop_order_id or "")
    if known_order_id:
        known_stop = _known_protective_stop_snapshot(known_order_id, option_symbol)
        if known_stop is None:
            return None
        if known_stop["active"]:
            if (
                current_position
                and current_position.option_symbol == option_symbol
                and str(current_position.protective_stop_status or "").upper()
                == "PENDING_VERIFICATION"
            ):
                verification_latency_ms = None
                requested_at = str(
                    current_position.protective_stop_verification_requested_at
                    or ""
                )
                if requested_at:
                    try:
                        requested = datetime.fromisoformat(requested_at)
                        if requested.tzinfo is None:
                            requested = requested.replace(tzinfo=timezone.utc)
                        verification_latency_ms = round(
                            (
                                datetime.now(timezone.utc)
                                - requested.astimezone(timezone.utc)
                            ).total_seconds()
                            * 1000.0,
                            3,
                        )
                    except (TypeError, ValueError):
                        verification_latency_ms = None
                current_position.protective_stop_status = "BROKER_VERIFIED"
                if float(known_stop.get("stop_price") or 0.0) > 0:
                    current_position.option_stop = float(known_stop["stop_price"])
                    current_position.protective_stop_price = float(
                        known_stop["stop_price"]
                    )
                save_position(current_position)
                verification_kind = str(
                    current_position.protective_stop_verification_kind
                    or "UNKNOWN"
                ).upper()
                record_stop_event(
                    (
                        "stop_ratchet_broker_verified"
                        if verification_kind == "RATCHET"
                        else "protective_stop_broker_verified"
                    ),
                    trade_key=(
                        f"{current_position.option_symbol}:"
                        f"{current_position.opened.isoformat()}"
                    ),
                    option_symbol=option_symbol,
                    broker_order_id=known_order_id,
                    broker_status=known_stop.get("status"),
                    broker_confirmed_stop=known_stop.get("stop_price"),
                    verification_latency_ms=verification_latency_ms,
                    verification_kind=verification_kind,
                )
            return True
        record_stop_event(
            "protective_stop_known_order_terminal",
            trade_key=(
                f"{current_position.option_symbol}:{current_position.opened.isoformat()}"
                if current_position
                else None
            ),
            option_symbol=option_symbol,
            broker_order_id=known_order_id,
            broker_status=known_stop.get("status"),
            recorded_stop_price=known_stop.get("stop_price"),
        )

    try:
        resp = _schwab_client.get_orders_for_account(_schwab_account_hash)
        resp.raise_for_status()
        orders = resp.json() if isinstance(resp.json(), list) else []
    except Exception as e:
        print(f"WARNING: Could not verify active protective stop: {e}")
        return None

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
            active_order_id = str(order.get("orderId") or "")
            raw_stop = order.get("stopPrice") or order.get("price") or 0.0
            try:
                active_stop_price = float(raw_stop)
            except (TypeError, ValueError):
                active_stop_price = 0.0
            if (
                current_position
                and current_position.option_symbol == option_symbol
                and active_order_id
                and active_order_id != known_order_id
            ):
                previous_order_id = str(current_position.protective_stop_order_id or "")
                previous_local_stop = float(current_position.option_stop or 0.0)
                current_position.protective_stop_order_id = active_order_id
                if active_stop_price > 0:
                    current_position.option_stop = active_stop_price
                    current_position.protective_stop_price = active_stop_price
                current_position.protective_stop_status = status
                save_position(current_position)
                record_stop_event(
                    "protective_stop_identity_recovered",
                    trade_key=(
                        f"{current_position.option_symbol}:"
                        f"{current_position.opened.isoformat()}"
                    ),
                    option_symbol=option_symbol,
                    rejected_or_terminal_order_id=previous_order_id,
                    recovered_broker_order_id=active_order_id,
                    recovered_stop_price=active_stop_price or None,
                    previous_local_stop=previous_local_stop,
                    broker_status=status,
                )
            return True

    return False


def _known_protective_stop_snapshot(order_id, option_symbol):
    """Return exact broker state for a known stop, or None if unavailable."""
    if not _schwab_client or not _schwab_account_hash or not order_id or not option_symbol:
        return None

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
        response = _schwab_client.get_order(str(order_id), _schwab_account_hash)
        response.raise_for_status()
        order = response.json() or {}
    except Exception as exc:
        print(f"WARNING: Could not verify known protective stop {order_id}: {exc}")
        return None

    is_protective_stop = (
        str(order.get("orderType") or "").upper()
        in {"STOP", "STOP_LIMIT", "TRAILING_STOP", "TRAILING_STOP_LIMIT"}
    )
    if is_protective_stop:
        is_protective_stop = any(
            leg.get("instrument", {}).get("assetType") == "OPTION"
            and leg.get("instrument", {}).get("symbol") == option_symbol
            and str(leg.get("instruction") or "").upper() == "SELL_TO_CLOSE"
            for leg in order.get("orderLegCollection", []) or []
        )

    raw_stop = order.get("stopPrice") or order.get("price") or 0.0
    try:
        stop_price = float(raw_stop)
    except (TypeError, ValueError):
        stop_price = 0.0
    status = str(order.get("status") or "").upper()
    return {
        "active": bool(is_protective_stop and status in active_statuses),
        "status": status,
        "stop_price": stop_price,
    }


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
    # fill that occurs after this position's entry time. A previously logged fill
    # is still authoritative proof that the broker position is closed; it means
    # reconciliation should clear stale local state without logging the trade a
    # second time.
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
            candidate_time = _order_time(order)
            if candidate_time and entry_time_hint and candidate_time < entry_time_hint:
                continue
            exit_candidates.append((
                candidate_time,
                order,
                _is_exit_order_already_logged(candidate_id),
            ))

    matched_exit_already_logged = False
    if exit_candidates:
        exit_candidates.sort(key=lambda item: item[0] or "")
        matched_exit = exit_candidates[0][1]
        matched_exit_already_logged = bool(exit_candidates[0][2])
        broker_exit_order_id = matched_exit.get("orderId")
        broker_exit_price = _extract_execution_price(matched_exit)
        broker_exit_time = _order_time(matched_exit) or broker_exit_time
    else:
        print(
            "WARNING: Broker shows no position but no matching post-entry "
            f"SELL_TO_CLOSE fill was found for {symbol}; preserving local state."
        )
        return

    if matched_exit_already_logged:
        clear_position()
        current_position = None
        _protective_stop_failed = False
        _protective_stop_failure_reason = None
        print(
            "✓ Cleared stale local position from already-logged broker exit "
            f"{broker_exit_order_id}"
        )
        print("✓ Protective stop failure lock cleared after broker reconciliation")
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
    record_option_management_cycle(
        current_position,
        spy_price=current_price,
        mark=option_exit_price,
        action=TradeAction.EXIT,
        reason="BROKER_RECONCILED_EXIT",
        event_type="broker_reconciled_exit_fill",
        broker_exit_order_id=broker_exit_order_id,
        broker_exit_fill_price=option_exit_price,
        protective_stop_trigger=current_position.option_stop,
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
    reconciled_audio_event_id = (
        f"exit:{broker_exit_order_id}"
        if broker_exit_order_id
        else f"exit:{symbol}:{broker_exit_time}"
    )
    _play_execution_alert(
        "exit",
        option_pnl_dollars,
        event_id=reconciled_audio_event_id,
    )
    _arm_post_exit_cooling(
        "BROKER_RECONCILED_EXIT",
        "broker_reconciliation",
        exit_event_id=(
            f"broker-exit:{broker_exit_order_id}"
            if broker_exit_order_id
            else f"broker-exit:{symbol}:{broker_exit_time}"
        ),
    )
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
    Calculate the canonical initial protective stop price from the option fill.
    
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
    
    print(f"   Protective Stop Calculation: {fill_price:.2f} * 96% = {stop_raw:.6f} → {stop_normalized:.2f}")
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
    existing_stop_price=None,
    skip_existing_order_scan=False,
):
    """
    Submit broker-held SELL_TO_CLOSE protective stop order.
    
    Uses a STOP market order with the canonical protective-stop trigger.
    
    Args:
        option_symbol: Exact Schwab option symbol (e.g., "SPY 260724C00754000")
        fill_price: Confirmed entry fill price
        quantity: Filled quantity
        stop_price_override: Optional explicit stop trigger to submit
        skip_existing_order_scan: Submit immediately for a freshly confirmed entry
        
    Returns:
        (order_id, stop_price) tuple on success
        (None, None) on failure
    """
    global _protective_stop_failed, _protective_stop_failure_reason
    trade_key = (
        f"{current_position.option_symbol}:{current_position.opened.isoformat()}"
        if current_position and current_position.option_symbol == option_symbol
        else None
    )
    
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

    existing_protective_stop = (
        (str(existing_stop_order_id), float(existing_stop_price or 0.0))
        if existing_stop_order_id
        else None
    )

    if existing_protective_stop:
        known_price = float(existing_protective_stop[1] or 0.0)
        if known_price > 0 and abs(known_price - float(stop_price)) < 0.005:
            print(
                f"✓ Known protective stop already active: "
                f"{existing_protective_stop[0]} @ ${known_price:.2f}"
            )
            record_stop_event(
                "protective_stop_restore_coalesced",
                trade_key=trade_key,
                option_symbol=option_symbol,
                quantity=quantity,
                stop_price=known_price,
                broker_order_id=existing_protective_stop[0],
                verification="last_confirmed",
            )
            return existing_protective_stop[0], known_price

    def _build_stop_order(target_stop_price):
        target_stop_price = normalize_option_tick(float(target_stop_price))

        from schwab.orders.generic import OrderBuilder
        from schwab.orders.common import OptionInstruction, Session, Duration, OrderType, OrderStrategyType

        order = (
            OrderBuilder()
            .set_session(Session.NORMAL)
            .set_duration(Duration.DAY)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .set_order_type(OrderType.STOP)
            .set_stop_price(str(target_stop_price))
            .add_option_leg(OptionInstruction.SELL_TO_CLOSE, option_symbol, quantity)
        )
        return order, target_stop_price

    def _accepted_order_id(response):
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
        return order_id

    def _submit_stop_once(target_stop_price):
        """Submit one STOP protective order and return its broker order ID."""
        order, target_stop_price = _build_stop_order(target_stop_price)
        response = _schwab_client.place_order(_schwab_account_hash, order)
        order_id = _accepted_order_id(response)
        return order_id, target_stop_price, order

    def _replace_stop_once(order_id, target_stop_price):
        """Atomically replace a known STOP in one broker request."""
        order, target_stop_price = _build_stop_order(target_stop_price)
        response = _schwab_client.replace_order(
            _schwab_account_hash,
            str(order_id),
            order,
        )
        replacement_id = _accepted_order_id(response)
        return replacement_id, target_stop_price, order
    
    try:
        # A known broker stop can be atomically replaced with one request. This
        # avoids the former verify + place + cancel sequence, which exhausted
        # Schwab's request budget during fast markets and delayed ratchets.
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
        if existing_protective_stop:
            existing_id, _existing_stop = existing_protective_stop
            print(f"   Atomically replacing known protective stop {existing_id}")
            order_id, submitted_stop_price, order = _replace_stop_once(existing_id, stop_price)
        else:
            order_id = submitted_stop_price = order = None
        if not existing_protective_stop and not skip_existing_order_scan:
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

        if existing_protective_stop and order_id is None:
            existing_id, _existing_stop = existing_protective_stop
            order_id, submitted_stop_price, order = _replace_stop_once(existing_id, stop_price)
        elif not existing_protective_stop:
            order_id, submitted_stop_price, order = _submit_stop_once(stop_price)
        
        if not order_id:
            print("WARNING: No order ID returned while submitting replacement stop")

            _protective_stop_failed = True
            _protective_stop_failure_reason = "No order ID returned"
            return None, None
        
        print(f"\n✓ PROTECTIVE STOP SUBMITTED to Schwab")
        print(f"   Order ID: {order_id}")
        print(f"   Type: SELL_TO_CLOSE STOP")
        print(f"   Symbol: {option_symbol}")
        print(f"   Quantity: {quantity}")
        print(f"   Stop Price: ${submitted_stop_price:.2f}")
        import json
        payload_str = json.dumps(order.__dict__, default=str)
        print(f"   Payload: {sanitize_for_logging(payload_str)}")

        _audit_bot_order(order_id, "PROTECTIVE_STOP")
        record_stop_event(
            "protective_stop_submitted",
            trade_key=trade_key,
            option_symbol=option_symbol,
            quantity=quantity,
            stop_price=submitted_stop_price,
            limit_price=None,
            broker_order_id=order_id,
            replaced_order_id=existing_protective_stop[0] if existing_protective_stop else None,
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
        
        if not existing_protective_stop:
            _protective_stop_failed = True
            _protective_stop_failure_reason = f"Submission failed: {error_msg}"
        record_stop_event(
            "protective_stop_submission_failed",
            trade_key=trade_key,
            option_symbol=option_symbol,
            quantity=quantity,
            requested_stop_price=stop_price,
            error=error_msg,
            http_status=status_code,
            response_text=response_text,
            existing_stop_order_id=(
                existing_protective_stop[0] if existing_protective_stop else None
            ),
            existing_stop_price=(
                existing_protective_stop[1] if existing_protective_stop else None
            ),
            protection_presumed_active=bool(existing_protective_stop),
        )
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

    if int(quantity) < 1 or int(quantity) > MAX_OPEN_CONTRACTS:
        print(
            f"ERROR: Entry quantity {quantity} is outside the permitted "
            f"range of 1-{MAX_OPEN_CONTRACTS} contracts"
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
            try:
                response_data = response.json() if response.text else {}
                order_id = response_data.get("id") or response_data.get("orderId")
            except Exception:
                order_id = None

        if not order_id:
            # A successful HTTP response means Schwab accepted the order even when
            # its Location header is missing. Return a sentinel so the caller
            # reconciles the broker position instead of submitting a duplicate.
            print("WARNING: Exit order accepted but no order ID returned; confirming via broker position")
            return "submitted-without-id"

        print(f"✓ EXIT ORDER SUBMITTED: SELL_TO_CLOSE MARKET {option_symbol} x{quantity} (Order {order_id})")
        _audit_bot_order(order_id, "EXIT_MARKET")
        return order_id
    except Exception as e:
        print(f"ERROR submitting exit market order: {e}")
        return None


_ACTIVE_EXIT_ORDER_STATUSES = {
    "PENDING_ACTIVATION",
    "ACCEPTED",
    "QUEUED",
    "WORKING",
    "PENDING_REPLACEMENT",
    "PARTIALLY_FILLED",
    "AWAITING_PARENT_ORDER",
    "AWAITING_CONDITION",
}


def _broker_option_long_quantity(option_symbol, positions):
    """Return Schwab's long quantity for one exact option symbol."""
    if positions is None:
        return None

    total = 0.0
    for position in positions:
        instrument = position.get("instrument", {}) or {}
        if instrument.get("assetType") != "OPTION":
            continue
        if str(instrument.get("symbol") or "") != str(option_symbol or ""):
            continue
        try:
            total += float(position.get("longQuantity") or 0.0)
        except (TypeError, ValueError):
            continue
    return max(0, int(total))


def _broker_long_spy_option_positions(positions):
    """Return exact Schwab symbols and quantities for open long SPY options."""
    by_symbol = {}
    for position in positions or []:
        instrument = position.get("instrument", {}) or {}
        symbol = str(instrument.get("symbol") or "")
        if instrument.get("assetType") != "OPTION" or not symbol.upper().startswith("SPY"):
            continue
        try:
            quantity = int(float(position.get("longQuantity") or 0.0))
        except (TypeError, ValueError):
            continue
        if quantity > 0:
            by_symbol[symbol] = by_symbol.get(symbol, 0) + quantity
    return sorted(by_symbol.items())


def _active_sell_to_close_order_ids(option_symbol, orders):
    """Return active broker orders that reserve contracts needed for a full exit."""
    order_ids = []
    for order in orders or []:
        if str(order.get("status") or "").upper() not in _ACTIVE_EXIT_ORDER_STATUSES:
            continue
        matching_leg = any(
            leg.get("instrument", {}).get("assetType") == "OPTION"
            and str(leg.get("instrument", {}).get("symbol") or "") == str(option_symbol or "")
            and str(leg.get("instruction") or "").upper() == "SELL_TO_CLOSE"
            for leg in order.get("orderLegCollection", []) or []
        )
        order_id = str(order.get("orderId") or "")
        if matching_leg and order_id and order_id not in order_ids:
            order_ids.append(order_id)
    return order_ids


def _cancel_active_option_exit_orders(option_symbol, orders, known_stop_order_id=None):
    """Release every active SELL_TO_CLOSE reservation before flattening."""
    order_ids = _active_sell_to_close_order_ids(option_symbol, orders)
    known_stop_order_id = str(known_stop_order_id or "")
    if known_stop_order_id and known_stop_order_id not in order_ids:
        known_stop = _known_protective_stop_snapshot(known_stop_order_id, option_symbol)
        terminal_statuses = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED", "REPLACED"}
        if (
            known_stop is None
            or known_stop.get("active")
            or str(known_stop.get("status") or "").upper() not in terminal_statuses
        ):
            order_ids.append(known_stop_order_id)

    for order_id in order_ids:
        if not _cancel_protective_stop(order_id):
            return False
    return True


def _wait_for_exit_fill(order_id, option_symbol, fallback_price, max_wait_seconds):
    """Confirm a closing order by broker fill status or an authoritative flat position."""
    if not _schwab_client or not order_id:
        print("ERROR: Cannot confirm exit without client and accepted order")
        return False, None

    started_at = time.time()
    check_interval = max(ORDER_CHECK_INTERVAL_SECONDS, 0.08)
    can_poll_order = str(order_id) != "submitted-without-id"
    last_fill_price = None

    while time.time() - started_at < max_wait_seconds:
        if can_poll_order:
            try:
                response = _schwab_client.get_order(order_id, _schwab_account_hash)
                response.raise_for_status()
                order = response.json() or {}
                status = str(order.get("status") or "").upper()
                print(f"  Exit order status: {status}")
                if status == "FILLED":
                    last_fill_price = _extract_execution_price(order)
                    if last_fill_price is None:
                        last_fill_price = float(fallback_price or 0.0) or None
                    return True, last_fill_price
                if status in {"REJECTED", "CANCELED", "CANCELLED", "EXPIRED"}:
                    return False, None
            except Exception as exc:
                print(f"WARNING: Could not poll exit order {order_id}: {exc}")
        else:
            positions, _, _, _ = get_schwab_positions()
            remaining = _broker_option_long_quantity(option_symbol, positions)
            if remaining == 0:
                return True, float(fallback_price or 0.0) or None
            time.sleep(max(check_interval, 0.25))
            continue

        time.sleep(check_interval)

    positions, _, _, _ = get_schwab_positions()
    remaining = _broker_option_long_quantity(option_symbol, positions)
    if remaining == 0:
        print(f"✓ Schwab confirms {option_symbol} is flat")
        return True, last_fill_price or (float(fallback_price or 0.0) or None)

    print(f"✗ Schwab still shows {remaining if remaining is not None else 'unknown'} contracts after exit timeout")
    return False, None


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
        # Start at the spread midpoint to protect price while still seeking a
        # prompt fill; close_trade falls back to market if it does not fill.
        target = bid + (0.50 * (ask - bid))
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
    global _last_entry_order_status, _last_entry_order_status_description
    _last_entry_order_status = None
    _last_entry_order_status_description = None

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
            _last_entry_order_status = status
            _last_entry_order_status_description = str(
                order_data.get("statusDescription") or ""
            ).strip() or None
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
                if _last_entry_order_status_description:
                    print(f"   Broker reason: {_last_entry_order_status_description}")
                return False, None
            
            elif status == "PENDING_ACTIVATION":
                print(f"  ⏳ Pending activation...")
            
            # Still waiting
            time.sleep(check_interval)
            
        except Exception as e:
            print(f"ERROR checking fill: {e}")
            # Continue trying
            time.sleep(check_interval)
    
    # TIMEOUT: Resolve the exact order first. A broad positions/orders snapshot
    # previously added about nine seconds to a subsecond entry timeout before
    # the bot could cancel and reprice.
    print(f"\n⏳ ORDER POLLING TIMEOUT after {max_wait_seconds}s")
    print("   Resolving exact order status before any account-wide reconciliation...")

    # Proactively cancel a working order so it cannot fill later outside bot
    # control. Confirm the exact order after cancellation to catch a fill race.
    needs_position_reconciliation = False
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

        if latest_status == "FILLED":
            fill_price = _extract_execution_price(latest_data)
            if fill_price is None:
                fill_price = float(limit_price or 0.0) or None
            print(f"✓ ORDER FILLED during timeout resolution: {option_symbol} at {fill_price}")
            return True, fill_price

        if latest_status in active_statuses:
            print(f"   Canceling timed-out entry order {order_id} (status {latest_status}) to prevent orphan fills")
            cancel_resp = _schwab_client.cancel_order(order_id, _schwab_account_hash)
            cancel_resp.raise_for_status()
            time.sleep(max(ORDER_CHECK_INTERVAL_SECONDS, 0.15))

            final = _schwab_client.get_order(order_id, _schwab_account_hash)
            final.raise_for_status()
            final_data = final.json() or {}
            final_status = str(final_data.get("status") or "").upper()
            if final_status == "FILLED":
                fill_price = _extract_execution_price(final_data)
                if fill_price is None:
                    fill_price = float(limit_price or 0.0) or None
                print(f"✓ ORDER FILLED during timeout/cancel race: {option_symbol} at {fill_price}")
                return True, fill_price
            needs_position_reconciliation = final_status not in {
                "CANCELED",
                "CANCELLED",
                "REJECTED",
                "EXPIRED",
            }
        elif latest_status not in {"CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}:
            needs_position_reconciliation = True
    except Exception as e:
        print(f"WARNING: Timed-out entry cancel/reconcile failed: {e}")
        needs_position_reconciliation = True

    if needs_position_reconciliation:
        try:
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
            print(f"WARNING: Final position reconciliation failed: {e}")

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
    global _last_protective_stop_check_epoch, _last_protective_stop_check_ok

    open_trade_start_ms = _perf_ms_now()
    metrics = {
        "attempted": True,
        "opened": False,
        "block_reason": None,
        "requested_quantity": None,
        "selected_quantity": None,
        "available_option_buying_funds": None,
        "precheck_ms": None,
        "quote_compute_ms": None,
        "submit_order_ms": None,
        "wait_fill_ms": None,
        "reprice_submit_ms": None,
        "reprice_wait_ms": None,
        "initial_limit_price": None,
        "final_limit_price": None,
        "entry_price_cap": None,
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
    metrics["requested_quantity"] = quantity

    # Reuse only a very recent pre-close exposure snapshot; otherwise perform
    # the live broker check before any order submission.
    prefetched_exposure = _fresh_entry_exposure_preflight()
    if prefetched_exposure is None:
        has_exposure, exposure_details = check_spy_option_exposure()
    else:
        has_exposure, exposure_details = prefetched_exposure
        print("ENTRY PRECHECK: using fresh pre-close broker exposure snapshot")
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
    initial_limit_price = float(limit_price or 0.0)
    metrics["initial_limit_price"] = initial_limit_price
    metrics["final_limit_price"] = initial_limit_price
    metrics["entry_price_cap"] = normalize_option_tick(
        initial_limit_price + ENTRY_MAX_CHASE_DOLLARS
    )
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
    print(f"Requested Quantity: {quantity}")

    if not quote_ok:
        print(f"\n🔒 ENTRY BLOCKED: option quote is not fresh enough to trust")
        print(f"   Reason: {quote_block_reason}")
        print("   No order submitted; bot remains flat")
        return _finalize(False, f"quote_guard:{quote_block_reason}")

    available_option_funds = _get_available_option_buying_funds()
    metrics["available_option_buying_funds"] = available_option_funds
    if available_option_funds is None:
        print("\n🔒 ENTRY BLOCKED: could not verify Schwab option buying funds")
        print("   No order submitted; bot remains flat")
        return _finalize(False, "option_buying_power_unavailable")

    affordable_quantity = _max_affordable_option_contracts(
        available_option_funds,
        limit_price,
        requested_quantity=quantity,
    )
    if affordable_quantity < 1:
        print("\n🔒 ENTRY BLOCKED: insufficient funds for one option contract")
        print(
            f"   Available for long options: ${available_option_funds:,.2f} | "
            f"Per-contract cost: ${float(limit_price) * 100.0:,.2f}"
        )
        print("   No order submitted; bot remains flat")
        metrics["selected_quantity"] = 0
        return _finalize(False, "insufficient_option_buying_power")

    quantity = affordable_quantity
    metrics["selected_quantity"] = quantity
    print(
        f"Option Buying Funds: ${available_option_funds:,.2f} | "
        f"Affordable Quantity: {quantity}/{metrics['requested_quantity']}"
    )

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
        max_wait_seconds=max(0.2, float(ENTRY_LIMIT_MAX_WAIT_SECONDS or 0.35)),
    )
    metrics["wait_fill_ms"] = _elapsed_ms(wait_start_ms)
    primary_terminal_reason = _entry_terminal_block_reason(
        _last_entry_order_status,
        _last_entry_order_status_description,
    )

    if filled:
        metrics["filled_via"] = "limit"

    if not filled:
        if primary_terminal_reason:
            print(
                "✗ Entry order reached a terminal broker status; "
                "repricing and market fallback suppressed"
            )
        else:
            refreshed_limit, refreshed_quote = _compute_fast_entry_limit_price(
                option_symbol,
                option_mark,
            )
            entry_price_cap = float(metrics["entry_price_cap"] or 0.0)
            refreshed_quote_ok, refreshed_quote_reason = (
                _validate_entry_quote_snapshot(refreshed_quote)
            )
            if (
                refreshed_quote_ok
                and float(refreshed_limit or 0.0) > 0
                and float(refreshed_limit) <= entry_price_cap
            ):
                limit_price = float(refreshed_limit)
                metrics["final_limit_price"] = limit_price
                print(
                    "⚠ LIMIT ENTRY MISSED: submitting one refreshed "
                    f"marketable limit @ ${limit_price:.2f} "
                    f"(hard cap ${entry_price_cap:.2f})"
                )
                reprice_submit_start_ms = _perf_ms_now()
                repriced_order_id = _submit_option_order(
                    option_symbol,
                    direction,
                    limit_price,
                    quantity,
                )
                metrics["reprice_submit_ms"] = _elapsed_ms(
                    reprice_submit_start_ms
                )
                if repriced_order_id:
                    _pending_order_id = repriced_order_id
                    reprice_wait_start_ms = _perf_ms_now()
                    filled, fill_price = _wait_for_fill(
                        repriced_order_id,
                        option_symbol,
                        limit_price,
                        max_wait_seconds=max(
                            0.2,
                            float(ENTRY_REPRICE_MAX_WAIT_SECONDS or 0.35),
                        ),
                    )
                    metrics["reprice_wait_ms"] = _elapsed_ms(
                        reprice_wait_start_ms
                    )
                    if filled:
                        order_id = repriced_order_id
                        metrics["filled_via"] = "repriced_limit"
            else:
                reason_text = (
                    refreshed_quote_reason
                    if not refreshed_quote_ok
                    else (
                        f"refreshed ask ${float(refreshed_limit or 0.0):.2f} "
                        f"exceeds cap ${entry_price_cap:.2f}"
                    )
                )
                print(f"🔒 ENTRY PRICE CHASE BLOCKED: {reason_text}")

        if not filled and ENTRY_MARKET_FALLBACK_ENABLED:
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
                    max_wait_seconds=max(0.2, float(ENTRY_MARKET_FALLBACK_MAX_WAIT_SECONDS or 0.35)),
                )
                metrics["market_fallback_wait_ms"] = _elapsed_ms(fallback_wait_start_ms)
                if filled:
                    order_id = market_order_id
                    metrics["filled_via"] = "market_fallback"

        if not filled:
            fallback_terminal_reason = _entry_terminal_block_reason(
                _last_entry_order_status,
                _last_entry_order_status_description,
            )
            final_block_reason = (
                primary_terminal_reason
                or fallback_terminal_reason
                or "entry_not_filled_within_price_cap"
            )
            print(f"✗ FAILED: Entry not opened ({final_block_reason})")
            print("✓ No position created (kept bot flat)")
            # Clear entry pending lock - next attempt can try again
            _entry_pending = False
            _pending_order_id = None
            return _finalize(False, final_block_reason)

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
    protective_stop_id, protective_stop_price = _submit_protective_stop(
        option_symbol,
        float(fill_price),
        quantity,
        skip_existing_order_scan=True,
    )
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
        print(f"\n✓ Protective stop submitted; broker verification pending")

    feature_payload = attach_entry_quote_telemetry(
        feature_payload,
        quote_snapshot=quote_levels,
        submitted_limit_price=limit_price,
        broker_fill_price=fill_price,
        filled_via=metrics.get("filled_via"),
        initial_limit_price=metrics.get("initial_limit_price"),
        price_cap=metrics.get("entry_price_cap"),
    )

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
        protective_stop_status=(
            "PENDING_VERIFICATION" if protective_stop_id else "FAILED"
        ),
        protective_stop_verification_requested_at=(
            datetime.now(timezone.utc).isoformat()
            if protective_stop_id
            else ""
        ),
        protective_stop_verification_kind=(
            "INITIAL" if protective_stop_id else ""
        ),
        option_high_since_entry=float(fill_price),
        option_low_since_entry=float(fill_price),
        option_trailing_high_bid=float(fill_price),
        option_high_timestamp=fill_timestamp,
        option_low_timestamp=fill_timestamp,
        spy_price_at_option_high=float(price),
        spy_price_at_option_low=float(price),
    )
    if protective_stop_id:
        _last_protective_stop_check_epoch = 0.0
        _last_protective_stop_check_ok = True

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

    _play_execution_alert("entry", event_id=f"entry:{order_id}")

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


def close_trade(
    price,
    reason,
    option_mark=None,
    execution_mode="market",
    limit_price=None,
    fallback_to_market=True,
    option_bid=None,
    option_last=None,
    quote_metadata=None,
):
    """
    Close a live trade on Schwab.
    
    CRITICAL SEQUENCE:
    1. Read the full position quantity from Schwab
    2. Cancel active SELL_TO_CLOSE orders that reserve those contracts
    3. Submit the full-position close and confirm Schwab is flat
    4. Clear local position
    5. Log the trade (failure won't prevent closure)
    """
    global current_position, _protective_stop_failed, _protective_stop_failure_reason
    global _last_exit_submission_failure_epoch

    if not current_position:
        return False

    pre_exit_option_mark = option_mark
    is_manual_exit = str(reason or "").upper().startswith("MANUAL_EXIT")
    retry_cooldown = 1.0 if is_manual_exit else EXIT_SUBMISSION_RETRY_COOLDOWN_SECONDS
    retry_in = retry_cooldown - (time.time() - _last_exit_submission_failure_epoch)
    if retry_in > 0:
        print(f"EXIT SUBMISSION COOLDOWN: retry available in {retry_in:.1f}s; protective stop remains active")
        return False

    # Save position data before clearing (for logging and stop cancellation)
    saved_position = current_position
    
    exit_order_id = None
    if saved_position.option_symbol and int(saved_position.quantity or 0) > 0:
        positions, active_orders, _, broker_error = get_schwab_positions()
        broker_quantity = _broker_option_long_quantity(saved_position.option_symbol, positions)
        broker_spy_positions = _broker_long_spy_option_positions(positions)
        if broker_quantity == 0 and len(broker_spy_positions) == 1:
            broker_symbol, broker_quantity = broker_spy_positions[0]
            if broker_symbol != saved_position.option_symbol:
                print(
                    "EXIT RECONCILIATION: local contract is stale; "
                    f"using Schwab position {broker_symbol} x{broker_quantity}"
                )
                saved_position.option_symbol = broker_symbol
        elif broker_quantity == 0 and len(broker_spy_positions) > 1:
            _last_exit_submission_failure_epoch = time.time()
            print(
                "❌ EXIT BLOCKED: Schwab shows multiple SPY option symbols; "
                "refusing to guess which position belongs to this trade"
            )
            return False

        if broker_quantity == 0:
            print("✓ Schwab already confirms the option position is flat")
            exit_quantity = 0
        else:
            exit_quantity = int(broker_quantity or saved_position.quantity or 0)
            if broker_quantity is None:
                print(f"WARNING: Broker quantity unavailable ({broker_error}); using local quantity {exit_quantity}")
            else:
                print(f"EXIT RECONCILIATION: Schwab holds {exit_quantity} contract(s); closing all")
                saved_position.quantity = exit_quantity

        if exit_quantity > 0:
            print("[STEP 1] Canceling active SELL_TO_CLOSE reservations before full-position exit...")
            reservations_cleared = _cancel_active_option_exit_orders(
                saved_position.option_symbol,
                active_orders,
                saved_position.protective_stop_order_id,
            )
            if not reservations_cleared:
                _last_exit_submission_failure_epoch = time.time()
                print("❌ EXIT BLOCKED: could not release an active closing order; retrying without risking over-close")
                return False
            saved_position.protective_stop_order_id = ""
            saved_position.protective_stop_status = "CANCELED_FOR_EXIT"
            save_position(saved_position)

        use_limit_mode = str(execution_mode or "market").lower() == "limit_near_market"
        if exit_quantity > 0 and use_limit_mode:
            if limit_price is None:
                limit_price = _compute_fast_exit_limit_price(saved_position.option_symbol, option_mark or saved_position.option_entry)
            print(f"[STEP 2] Submitting SELL_TO_CLOSE limit exit near market @ ${float(limit_price or 0):.2f}...")
            exit_order_id = _submit_option_exit_limit_order(
                saved_position.option_symbol,
                exit_quantity,
                float(limit_price or 0.0),
            )
        elif exit_quantity > 0:
            print("[STEP 2] Submitting full-position SELL_TO_CLOSE market exit at the best available price...")
            exit_order_id = _submit_option_exit_market_order(
                saved_position.option_symbol,
                exit_quantity,
            )

        if exit_quantity > 0 and not exit_order_id:
            if use_limit_mode and fallback_to_market:
                print("WARNING: Limit exit submission failed, falling back to market exit")
                exit_order_id = _submit_option_exit_market_order(
                    saved_position.option_symbol,
                    exit_quantity,
                )

        if exit_quantity > 0 and not exit_order_id:
            _last_exit_submission_failure_epoch = time.time()
            print("❌ EXIT SUBMISSION FAILED: restoring protection and keeping position open for retry")
            restored_stop_id, restored_stop_price = _submit_protective_stop(
                saved_position.option_symbol,
                float(saved_position.option_entry or 0.0),
                exit_quantity,
                stop_price_override=float(saved_position.option_stop or 0.0),
            )
            if restored_stop_id:
                saved_position.protective_stop_order_id = str(restored_stop_id)
                saved_position.protective_stop_price = float(restored_stop_price or saved_position.option_stop or 0.0)
                saved_position.protective_stop_status = "PLACED"
                save_position(saved_position)
            return False

        _last_exit_submission_failure_epoch = 0.0

        filled, exit_fill = (True, option_mark) if exit_quantity == 0 else _wait_for_exit_fill(
            exit_order_id,
            saved_position.option_symbol,
            float(limit_price or option_mark or 0.0),
            max_wait_seconds=12 if use_limit_mode else ORDER_SUBMISSION_TIMEOUT_SECONDS,
        )
        if not filled:
            if use_limit_mode and fallback_to_market:
                print("WARNING: Limit exit not filled quickly, falling back to market exit")
                refreshed_positions, refreshed_orders, _, _ = get_schwab_positions()
                remaining_quantity = _broker_option_long_quantity(saved_position.option_symbol, refreshed_positions)
                remaining_quantity = int(remaining_quantity or 0)
                if remaining_quantity > 0 and _cancel_active_option_exit_orders(
                    saved_position.option_symbol,
                    refreshed_orders,
                ):
                    market_exit_id = _submit_option_exit_market_order(
                        saved_position.option_symbol,
                        remaining_quantity,
                    )
                    if market_exit_id:
                        filled, exit_fill = _wait_for_exit_fill(
                            market_exit_id,
                            saved_position.option_symbol,
                            float(option_mark or 0.0),
                            max_wait_seconds=ORDER_SUBMISSION_TIMEOUT_SECONDS,
                        )
                        exit_order_id = market_exit_id if filled else exit_order_id

        if not filled:
            print("❌ EXIT FILL FAILED/TIMEOUT: keeping position open for retry/reconciliation")
            remaining_positions, _, _, _ = get_schwab_positions()
            remaining_quantity = _broker_option_long_quantity(saved_position.option_symbol, remaining_positions)
            remaining_quantity = int(remaining_quantity or saved_position.quantity or 0)
            if remaining_quantity > 0 and saved_position.option_stop and saved_position.option_stop > 0:
                restored_stop_id, restored_stop_price = _submit_protective_stop(
                    saved_position.option_symbol,
                    float(saved_position.option_entry or 0.0),
                    remaining_quantity,
                    stop_price_override=float(saved_position.option_stop),
                )
                if restored_stop_id:
                    saved_position.quantity = remaining_quantity
                    saved_position.protective_stop_order_id = str(restored_stop_id)
                    saved_position.protective_stop_price = float(restored_stop_price or saved_position.option_stop)
                    saved_position.protective_stop_status = "PLACED"
                    save_position(saved_position)
            return False

        if exit_fill is not None:
            try:
                option_mark = float(exit_fill)
            except (TypeError, ValueError):
                pass

        record_option_management_cycle(
            saved_position,
            spy_price=price,
            bid=option_bid,
            ask=(quote_metadata or {}).get("ask"),
            mark=(
                (quote_metadata or {}).get("mark")
                or pre_exit_option_mark
            ),
            last=option_last,
            quote_metadata=quote_metadata,
            action=TradeAction.EXIT,
            reason=reason,
            event_type="exit_fill",
            broker_exit_order_id=exit_order_id,
            broker_exit_fill_price=option_mark,
            protective_stop_trigger=saved_position.option_stop,
        )
    
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
    exit_timestamp = datetime.now(EASTERN_TZ)
    update_option_extrema(
        saved_position,
        spy_price=price,
        bid=option_bid,
        last=option_last,
        mark=option_exit_price,
        observed_at=exit_timestamp,
    )
    quality = exit_quality_metrics(
        option_entry=option_entry_price,
        option_exit=option_exit_price,
        option_high=saved_position.option_high_since_entry,
        option_low=saved_position.option_low_since_entry,
        quantity=saved_position.quantity,
        entry_time=saved_position.opened,
        exit_time=exit_timestamp,
        high_timestamp=saved_position.option_high_timestamp,
    )
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

    record_option_management_cycle(
        saved_position,
        spy_price=price,
        bid=option_bid,
        mark=option_exit_price,
        last=option_last,
        action=TradeAction.EXIT,
        reason=reason,
        event_type="option_trade_closed",
        broker_exit_order_id=exit_order_id,
        observed_at=exit_timestamp,
    )

    # Record trade exit first (before logging)
    record_trade(pnl)
    print(f"🔴 LIVE CLOSE {reason}")  # Live mode indicator
    print(f"Exit: {price}")
    print(f"P&L: {pnl:.2f}")
    print(f"[LIVE MODE] Order closed on Schwab account")

    # Clear position from memory and disk BEFORE logging
    ledger_trade = {
        "entry_time": saved_position.opened.isoformat(),
        "exit_time": exit_timestamp.isoformat(),
        "direction": saved_position.direction,
        "entry_price": saved_position.entry_price,
        "exit_price": price,
        "pnl": pnl,
        "exit_reason": reason,
        "feature_payload": saved_position.feature_payload,
        "option_symbol": saved_position.option_symbol,
        "option_entry": option_entry_price,
        "option_exit": option_exit_price,
        "option_quantity": saved_position.quantity,
        "option_delta": saved_position.option_delta,
        "option_return": option_return,
        "option_pnl_dollars": option_pnl_dollars,
        "option_pnl_pct": option_pnl_pct,
        "broker_entry_order_id": str(saved_position.schwab_order_id or "") or None,
        "broker_exit_order_id": str(exit_order_id or "") or None,
        "momentum_freshness_score": momentum_freshness_score,
        "momentum_phase": momentum_phase,
        "absorption_score": absorption_score,
        "entry_diagnostic_snapshot": entry_diagnostic_snapshot,
        "exit_diagnostic_snapshot": exit_diagnostic_snapshot,
        "option_high_since_entry": saved_position.option_high_since_entry,
        "option_low_since_entry": saved_position.option_low_since_entry,
        "option_high_timestamp": saved_position.option_high_timestamp,
        "option_low_timestamp": saved_position.option_low_timestamp,
        "spy_price_at_option_high": saved_position.spy_price_at_option_high,
        "spy_price_at_option_low": saved_position.spy_price_at_option_low,
        "entry_efficiency_pct": None,
        "trade_quality_grade": None,
        **quality,
    }
    try:
        from execution.trade_ledger_outbox import queue_completed_trade

        queue_completed_trade(ledger_trade)
    except Exception as exc:
        print(f"WARNING: Could not queue completed trade for ledger recovery: {exc}")

    try:
        clear_position()
    except Exception as exc:
        print(f"WARNING: position file clear failed: {exc}")

    current_position = None
    # Clearing position resets alarm lock so new entries can resume while flat.
    _protective_stop_failed = False
    _protective_stop_failure_reason = None
    close_audio_event_id = (
        f"exit:{exit_order_id}"
        if exit_order_id
        else f"exit:{saved_position.schwab_order_id}:{exit_timestamp.isoformat()}"
    )
    _play_execution_alert(
        "exit",
        option_pnl_dollars,
        event_id=close_audio_event_id,
    )
    _arm_post_exit_cooling(
        reason,
        "live_engine",
        exit_event_id=close_audio_event_id,
    )
    
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

        safe_log_trade(**ledger_trade)
    except Exception as log_exc:
        print(f"\n⚠️  LOGGING ERROR (position already closed): {log_exc}")
        print(f"Position is CLOSED - logging failure does not affect trade")
        import traceback
        print("Traceback:")
        traceback.print_exc()
        # Continue - position is already closed, don't re-throw

    try:
        from execution.strategy_research import analyze_completed_trade

        analyze_completed_trade({
            "entry_time": saved_position.opened.isoformat(),
            "exit_time": exit_timestamp.isoformat(),
            "direction": saved_position.direction,
            "exit_reason": reason,
            "option_symbol": saved_position.option_symbol,
            "option_entry": option_entry_price,
            "option_exit": option_exit_price,
            "option_quantity": saved_position.quantity,
            "option_pnl_pct": option_pnl_pct * 100.0 if option_pnl_pct is not None else None,
            "broker_entry_order_id": str(saved_position.schwab_order_id or "") or None,
            "broker_exit_order_id": str(exit_order_id or "") or None,
            "entry_diagnostic_snapshot": entry_diagnostic_snapshot,
            "exit_diagnostic_snapshot": exit_diagnostic_snapshot,
            **quality,
        })
    except Exception as research_exc:
        print(f"WARNING: Strategy research analysis unavailable: {research_exc}")

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


def _stop_ratchet_quote_is_reliable(quote_metadata):
    """Reject only an upward stop update based on unreliable option quote facts."""
    metadata = quote_metadata or {}
    issues = []
    quote_age_seconds = metadata.get("quote_age_seconds")
    if quote_age_seconds is not None and float(quote_age_seconds) > STOP_RATCHET_MAX_QUOTE_AGE_SECONDS:
        issues.append("stale_quote")
    spread_pct = metadata.get("quote_spread_pct")
    if spread_pct is not None and float(spread_pct) > STOP_RATCHET_MAX_SPREAD_PCT:
        issues.append("wide_spread")
    bid = float(metadata.get("bid") or 0.0)
    ask = float(metadata.get("ask") or 0.0)
    if bid > 0 and ask > 0 and ask < bid:
        issues.append("crossed_quote")
    return not issues, issues


def manage_trade(current_price, option_mark=None, option_bid=None, option_last=None, quote_metadata=None):
    """Execute the canonical Brain management decision against Schwab."""
    global current_position, _protective_stop_failed, _protective_stop_failure_reason
    global _last_protective_stop_submission_epoch

    if not in_trade():
        return
    trade_key = f"{current_position.option_symbol}:{current_position.opened.isoformat()}"
    record_stop_event(
        "option_quote_observed",
        trade_key=trade_key,
        option_symbol=current_position.option_symbol,
        bid=option_bid,
        mark=option_mark,
        last=option_last,
        active_stop=current_position.option_stop,
        quote_metadata=quote_metadata or {},
    )
    extrema_updated = update_option_extrema(
        current_position,
        spy_price=current_price,
        bid=option_bid,
        last=option_last,
        mark=option_mark,
        observed_at=datetime.now(EASTERN_TZ),
    )
    quote_reliable_for_ratchet, _ = _stop_ratchet_quote_is_reliable(quote_metadata)
    reliable_bid = float(option_bid or 0.0)
    trailing_high_updated = False
    if (
        quote_reliable_for_ratchet
        and reliable_bid > float(current_position.option_trailing_high_bid or 0.0)
    ):
        current_position.option_trailing_high_bid = reliable_bid
        trailing_high_updated = True
    if _is_end_of_day_exit_due():
        record_option_management_cycle(
            current_position,
            spy_price=current_price,
            bid=option_bid,
            ask=(quote_metadata or {}).get("ask"),
            mark=option_mark,
            last=option_last,
            quote_metadata=quote_metadata,
            action=TradeAction.EXIT,
            reason="END_OF_DAY_EXIT",
        )
        close_trade(
            current_price,
            "END_OF_DAY_EXIT",
            option_mark,
            option_bid=option_bid,
            option_last=option_last,
            quote_metadata=quote_metadata,
        )
        return
    _sync_position_with_broker(current_price)
    if not in_trade():
        return

    global _last_protective_stop_check_epoch, _last_protective_stop_check_ok
    now_epoch = time.time()
    should_check_stop = (
        (now_epoch - float(_last_protective_stop_check_epoch or 0.0))
        >= max(0.25, float(PROTECTIVE_STOP_CHECK_MIN_INTERVAL_SECONDS or 3.0))
    )
    if should_check_stop and current_position.option_symbol:
        verified_stop = _has_active_protective_stop_order(current_position.option_symbol)
        _last_protective_stop_check_epoch = now_epoch
        if verified_stop is None:
            protective_stop_active = bool(current_position.protective_stop_order_id)
            record_stop_event(
                "protective_stop_verification_unavailable",
                trade_key=trade_key,
                option_symbol=current_position.option_symbol,
                active_stop=current_position.protective_stop_price,
                quote_metadata=quote_metadata or {},
            )
        else:
            protective_stop_active = bool(verified_stop)
            _last_protective_stop_check_ok = protective_stop_active
    else:
        protective_stop_active = bool(_last_protective_stop_check_ok)

    decision = LIVE_BRAIN.manage_trade(
        current_position,
        {
            "current_price": current_price,
            "option_mark": option_mark,
            "option_bid": option_bid,
            "option_trailing_high_bid": current_position.option_trailing_high_bid,
            "protective_stop_active": protective_stop_active,
            "now": datetime.now(),
        },
    )
    previous_option_stop = current_position.option_stop
    for field_name, value in decision.metadata.get("state_updates", {}).items():
        setattr(current_position, field_name, value)

    record_stop_event(
        "stop_management_decision",
        trade_key=trade_key,
        option_symbol=current_position.option_symbol,
        action=str(decision.action),
        reason=decision.reason,
        prior_stop=previous_option_stop,
        candidate_stop=decision.stop_price,
        broker_confirmed_stop=current_position.protective_stop_price,
        trailing_high_bid=current_position.option_trailing_high_bid,
        ratchet_lag_dollars=(
            round(
                max(
                    0.0,
                    float(decision.stop_price or 0.0)
                    - float(current_position.protective_stop_price or previous_option_stop or 0.0),
                ),
                6,
            )
            if decision.stop_price is not None
            else 0.0
        ),
        bid=option_bid,
        mark=option_mark,
        quote_metadata=quote_metadata or {},
    )
    record_option_management_cycle(
        current_position,
        spy_price=current_price,
        bid=option_bid,
        ask=(quote_metadata or {}).get("ask"),
        mark=option_mark,
        last=option_last,
        quote_metadata=quote_metadata,
        action=decision.action,
        reason=decision.reason,
    )

    if decision.action is TradeAction.RESTORE_PROTECTIVE_STOP:
        restore_symbol = current_position.option_symbol
        # A broker stop fill can race the normal throttled reconciliation. Force
        # one final position check so a flat account never receives another
        # SELL_TO_CLOSE stop after its exit has already filled.
        _sync_position_with_broker(current_price, force=True)
        if not in_trade():
            record_stop_event(
                "protective_stop_restore_skipped_flat",
                trade_key=trade_key,
                option_symbol=restore_symbol,
            )
            return
        _send_unprotected_position_alert(current_position.option_symbol, decision.quantity, decision.stop_price)
        order_id, submitted_stop = _submit_protective_stop(
            current_position.option_symbol,
            float(current_position.option_entry or 0.0),
            int(decision.quantity or 0),
            stop_price_override=float(decision.stop_price or 0.0),
        )
        if not order_id:
            _protective_stop_failed = True
            _protective_stop_failure_reason = "Protective-stop verification/restore failed; manual broker verification required"
            protection_decision = LIVE_BRAIN.evaluate_protective_stop_result(
                current_position,
                restored=False,
                restore_count=int(current_position.protective_stop_restore_count or 0),
            )
            close_trade(
                current_price,
                protection_decision.reason,
                option_mark,
                option_bid=option_bid,
                option_last=option_last,
                quote_metadata=quote_metadata,
            )
            return
        current_position.protective_stop_order_id = str(order_id)
        current_position.protective_stop_price = float(submitted_stop or decision.stop_price or 0.0)
        current_position.protective_stop_status = "PENDING_VERIFICATION"
        current_position.protective_stop_verification_requested_at = (
            datetime.now(timezone.utc).isoformat()
        )
        current_position.protective_stop_verification_kind = "RESTORE"
        current_position.protective_stop_restore_count = int(current_position.protective_stop_restore_count or 0) + 1
        _last_protective_stop_check_ok = True
        _last_protective_stop_check_epoch = 0.0
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
        quote_reliable, quote_issues = _stop_ratchet_quote_is_reliable(quote_metadata)
        if not quote_reliable:
            current_position.option_stop = previous_option_stop
            record_stop_event(
                "stop_ratchet_skipped_unreliable_quote",
                trade_key=trade_key,
                option_symbol=current_position.option_symbol,
                prior_stop=previous_option_stop,
                candidate_stop=decision.stop_price,
                issues=quote_issues,
                quote_metadata=quote_metadata or {},
            )
            save_position(current_position)
            return
        stop_improvement = float(decision.stop_price or 0.0) - float(previous_option_stop or 0.0)
        seconds_since_last_submission = time.time() - float(_last_protective_stop_submission_epoch or 0.0)
        broker_cooldown_remaining = max(0.0, float(_broker_rate_limited_until_epoch or 0.0) - time.time())
        if (
            stop_improvement < STOP_RATCHET_MIN_IMPROVEMENT_DOLLARS
            or seconds_since_last_submission < STOP_RATCHET_MIN_INTERVAL_SECONDS
            or broker_cooldown_remaining > 0
        ):
            deferral_reasons = []
            if stop_improvement < STOP_RATCHET_MIN_IMPROVEMENT_DOLLARS:
                deferral_reasons.append("minimum_improvement")
            if seconds_since_last_submission < STOP_RATCHET_MIN_INTERVAL_SECONDS:
                deferral_reasons.append("minimum_interval")
            if broker_cooldown_remaining > 0:
                deferral_reasons.append("broker_rate_limit")
            current_position.option_stop = previous_option_stop
            record_stop_event(
                "stop_ratchet_deferred",
                trade_key=trade_key,
                option_symbol=current_position.option_symbol,
                prior_stop=previous_option_stop,
                candidate_stop=decision.stop_price,
                trailing_high_bid=current_position.option_trailing_high_bid,
                stop_improvement=stop_improvement,
                minimum_improvement=STOP_RATCHET_MIN_IMPROVEMENT_DOLLARS,
                seconds_since_last_submission=seconds_since_last_submission,
                minimum_interval_seconds=STOP_RATCHET_MIN_INTERVAL_SECONDS,
                broker_cooldown_remaining_seconds=broker_cooldown_remaining,
                deferral_reasons=deferral_reasons,
                quote_metadata=quote_metadata or {},
            )
            save_position(current_position)
            return
        current_executable = float(option_bid or option_mark or 0.0)
        if current_executable <= (
            float(decision.stop_price or 0.0)
            + STOP_RATCHET_MARKET_BUFFER_DOLLARS
        ):
            record_stop_event(
                "stop_ratchet_high_water_crossed",
                trade_key=trade_key,
                option_symbol=current_position.option_symbol,
                prior_stop=previous_option_stop,
                candidate_stop=decision.stop_price,
                trailing_high_bid=current_position.option_trailing_high_bid,
                bid=option_bid,
                mark=option_mark,
                market_buffer_dollars=STOP_RATCHET_MARKET_BUFFER_DOLLARS,
                quote_metadata=quote_metadata or {},
            )
            current_position.option_stop = previous_option_stop
            close_trade(
                current_price,
                decision.reason,
                option_mark,
                option_bid=option_bid,
                option_last=option_last,
                quote_metadata=quote_metadata,
            )
            return
        submission_started = time.perf_counter()
        order_id, submitted_stop = _submit_protective_stop(
            current_position.option_symbol,
            float(current_position.option_entry or 0.0),
            int(decision.quantity or 0),
            stop_price_override=float(decision.stop_price or 0.0),
            existing_stop_order_id=current_position.protective_stop_order_id or None,
            existing_stop_price=current_position.protective_stop_price or None,
        )
        if not order_id:
            current_position.option_stop = previous_option_stop
            record_stop_event(
                "stop_ratchet_submission_failed",
                trade_key=trade_key,
                option_symbol=current_position.option_symbol,
                prior_stop=previous_option_stop,
                candidate_stop=decision.stop_price,
                quote_metadata=quote_metadata or {},
            )
            save_position(current_position)
            return
        ratchet_submission_ms = round(
            (time.perf_counter() - submission_started) * 1000.0,
            3,
        )
        current_position.protective_stop_order_id = str(order_id)
        current_position.option_stop = float(
            submitted_stop or decision.stop_price or previous_option_stop or 0.0
        )
        current_position.protective_stop_price = current_position.option_stop
        current_position.protective_stop_status = "PENDING_VERIFICATION"
        current_position.protective_stop_verification_requested_at = (
            datetime.now(timezone.utc).isoformat()
        )
        current_position.protective_stop_verification_kind = "RATCHET"
        current_position.active_stop_reason = decision.reason
        _last_protective_stop_submission_epoch = time.time()
        # The replacement endpoint can return a new order ID before Schwab
        # asynchronously accepts or rejects it. Force the next management cycle
        # to verify that exact ID and recover the still-working prior stop if the
        # replacement was rejected.
        _last_protective_stop_check_epoch = 0.0
        _last_protective_stop_check_ok = True
        record_stop_event(
            "stop_ratchet_submission_accepted_pending_verification",
            trade_key=trade_key,
            option_symbol=current_position.option_symbol,
            prior_stop=previous_option_stop,
            desired_stop=decision.stop_price,
            submitted_stop=current_position.option_stop,
            trailing_high_bid=current_position.option_trailing_high_bid,
            broker_order_id=current_position.protective_stop_order_id,
            submission_latency_ms=ratchet_submission_ms,
            verification_due_next_cycle=True,
            quote_metadata=quote_metadata or {},
        )
        save_position(current_position)
        return

    if decision.action is TradeAction.EXIT:
        close_trade(
            current_price,
            decision.reason,
            decision.metadata.get("exit_option_mark") or option_mark,
            option_bid=option_bid,
            option_last=option_last,
            quote_metadata=quote_metadata,
        )
        return

    if decision.metadata.get("state_updates") or extrema_updated or trailing_high_updated:
        save_position(current_position)


def _is_end_of_day_exit_due(now_et=None):
    now_et = now_et or datetime.now(EASTERN_TZ)
    return now_et.weekday() < 5 and now_et.time() >= ENTRY_CUTOFF_TIME
