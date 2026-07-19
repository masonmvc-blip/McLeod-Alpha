from execution.position_store import save_position, load_position, clear_position
from execution.sms_alerts import send_trade_entry_alert, send_trade_exit_alert

from dataclasses import dataclass
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
from execution.risk_manager import can_open_trade, record_trade, record_stop
from execution.trade_logger import log_trade, log_trade_diagnostic_event
import json

EASTERN_TZ = ZoneInfo("America/New_York")


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


def _extract_momentum_fields(feature_payload_text):
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
    if not feature_payload_text:
        return None
    try:
        payload = json.loads(feature_payload_text)
        snapshot = {
            "captured_at": payload.get("captured_at") or datetime.now(EASTERN_TZ).isoformat(),
            "trend_stage": payload.get("trend_stage"),
            "continuation_quality_score": payload.get("continuation_quality_score"),
            "momentum_acceleration_score": payload.get("momentum_acceleration_score"),
            "absorption_score": payload.get("absorption_score"),
            "confidence_score": payload.get("confidence_score"),
            "trend_lifecycle_call": payload.get("trend_lifecycle_call"),
            "trend_lifecycle_put": payload.get("trend_lifecycle_put"),
            "continuation_quality_call": payload.get("continuation_quality_call"),
            "continuation_quality_put": payload.get("continuation_quality_put"),
            "trend_stage_call": payload.get("trend_stage_call"),
            "trend_stage_put": payload.get("trend_stage_put"),
            "confidence_score_call": payload.get("confidence_score_call"),
            "confidence_score_put": payload.get("confidence_score_put"),
        }
        return json.dumps(snapshot)
    except Exception:
        return None


def _build_exit_diagnostic_snapshot(*, direction, reason, underlying_entry, underlying_exit, option_entry, option_exit):
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
            "source": "PAPER_CLOSE",
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


TWO_PCT_TRIGGER_PCT = 2        # Set stop to 3% below entry at 2% profit
TWO_PCT_ENTRY_STOP_PCT = 3     # Entry-anchored stop distance at 2% trigger
THREE_PCT_TRIGGER_PCT = 3      # Set stop to 1% below entry at 3% profit
THREE_PCT_ENTRY_STOP_PCT = 1   # Entry-anchored stop distance at 3% trigger
TRAIL_5_TRIGGER_PCT = 4        # Trail 3% at 4% profit
TRAIL_4_TRIGGER_PCT = 5        # Trail 2.5% at 5% profit
TRAIL_3_TRIGGER_PCT = 6        # Trail 2% at 6% profit
TRAIL_2_TRIGGER_PCT = 7        # Trail 2.5% at 7% profit
TRAIL_1_TRIGGER_PCT = 8        # Trail 1% at 8% profit
INITIAL_STOP_LOSS_PCT = -5      # Initial stop: 5% below entry

OPTION_PROFIT_TARGET_PCT = 5
OPTION_STOP_LOSS_PCT = -5

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

current_position = None
current_position = load_position(Position)
trade_log = []


def in_trade():
    global current_position

    if current_position is None:
        persisted = load_position(Position)
        if persisted is not None:
            current_position = persisted

    return current_position is not None


def open_trade(direction, price, stop, target, quantity, reason, option=None, feature_payload=None):
    global current_position

    if in_trade():
        print("Trade skipped: already in a position.")
        return False

    allowed, block_reason = can_open_trade()
    if not allowed:
        print(f"Trade blocked: {block_reason}")
        return False

    current_position = Position(
        direction=direction,
        entry_price=price,
        stop_price=stop,
        target_price=target,
        quantity=quantity,
        opened=datetime.now(EASTERN_TZ),
        reason=reason,
        option_symbol=option.get("symbol") if option else None,
        option_entry=option.get("mark") if option else 0.0,
        option_delta=option.get("delta") if option else 0.0,
        feature_payload=feature_payload or "",
    )

    try:
        save_position(current_position)
    except Exception as exc:
        print(f"WARNING: position file save failed: {exc}")

    print(f"DEBUG after open current_position = {current_position}")
    print(f"PAPER {direction}")
    print(f"Entry: {price}")
    print(f"Stop: {stop}")
    print(f"Target: {target}")

    if option:
        print(f"Option: {option.get('symbol')}")
        print(f"Option entry mark: {option.get('mark')}")
        print(f"Delta: {option.get('delta')}")

    send_trade_entry_alert(
        mode="PAPER",
        direction=direction,
        quantity=int(quantity or 0),
        option_symbol=(option or {}).get("symbol", ""),
        option_entry=float((option or {}).get("mark", 0.0) or 0.0),
        spy_entry=float(price or 0.0),
        reason=reason,
    )

    try:
        log_trade_diagnostic_event(
            event_type="ENTRY",
            direction=direction,
            option_symbol=(option or {}).get("symbol", ""),
            source="PAPER",
            snapshot=_extract_entry_diagnostic_snapshot(feature_payload or "") or (feature_payload or ""),
        )
    except Exception as e:
        print(f"WARNING: Could not persist PAPER ENTRY diagnostic snapshot: {e}")

    return True

def close_trade(price, reason, option_mark=None):
    global current_position

    if not current_position:
        return False

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
        "closed": datetime.now(EASTERN_TZ),
    })

    # Calculate option-specific metrics
    option_entry_price = float(current_position.option_entry or 0)
    option_exit_price = float(option_mark or 0)
    option_contracts = int(current_position.quantity or 1)
    
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
            option_exit_price - option_entry_price
        ) * 100 * option_contracts
        option_pnl_pct = (
            (option_exit_price - option_entry_price)
            / option_entry_price
        ) * 100

    momentum_freshness_score, momentum_phase = _extract_momentum_fields(current_position.feature_payload)
    absorption_score = _extract_absorption_score(current_position.feature_payload, current_position.direction)
    entry_diagnostic_snapshot = _extract_entry_diagnostic_snapshot(current_position.feature_payload)
    exit_diagnostic_snapshot = _build_exit_diagnostic_snapshot(
        direction=current_position.direction,
        reason=reason,
        underlying_entry=current_position.entry_price,
        underlying_exit=price,
        option_entry=option_entry_price,
        option_exit=option_exit_price,
    )

    try:
        log_trade_diagnostic_event(
            event_type="EXIT",
            direction=current_position.direction,
            option_symbol=current_position.option_symbol,
            source="PAPER",
            snapshot=exit_diagnostic_snapshot,
        )
    except Exception as e:
        print(f"WARNING: Could not persist PAPER EXIT diagnostic snapshot: {e}")

    safe_log_trade(
        entry_time=current_position.opened.isoformat(),
        exit_time=datetime.now(EASTERN_TZ).isoformat(),
        direction=current_position.direction,
        entry_price=current_position.entry_price,
        exit_price=price,
        pnl=pnl,
        exit_reason=reason,
        feature_payload=current_position.feature_payload,
        option_symbol=current_position.option_symbol,
        option_entry=current_position.option_entry,
        option_exit=option_mark,
        option_quantity=option_contracts,
        option_delta=current_position.option_delta,
        option_return=option_return,
        option_pnl_dollars=option_pnl_dollars,
        option_pnl_pct=option_pnl_pct,
        momentum_freshness_score=momentum_freshness_score,
        momentum_phase=momentum_phase,
        absorption_score=absorption_score,
        entry_diagnostic_snapshot=entry_diagnostic_snapshot,
        exit_diagnostic_snapshot=exit_diagnostic_snapshot,
    )

    if option_entry_price > 0 and option_exit_price > 0:
        print(
            f'OPTION RESULT | '
            f'PnL=${option_pnl_dollars:.2f} | '
            f'Return={option_pnl_pct:.2f}% | '
            f'Contracts={option_contracts}'
        )

    record_trade(pnl)

    if reason == "STOP":
        record_stop()

    print()
    print("========== TRADE CLOSED ==========")
    print(f"Reason: {reason}")
    print(f"Underlying PnL: ${pnl:.2f}")

    if current_position.option_entry and option_mark:
        option_pct = ((option_mark - current_position.option_entry) / current_position.option_entry) * 100

        print(f"Option Entry: {current_position.option_entry:.2f}")
        print(f"Option Exit : {option_mark:.2f}")
        print(f"Option Return: {option_pct:.1f}%")

    print("==================================")

    send_trade_exit_alert(
        mode="PAPER",
        direction=current_position.direction,
        quantity=int(current_position.quantity or 0),
        option_symbol=current_position.option_symbol or "",
        option_entry=float(current_position.option_entry or 0.0),
        option_exit=float(option_mark or 0.0),
        pnl_dollars=float(option_pnl_dollars or 0.0),
        pnl_pct=float(option_pnl_pct or 0.0),
        exit_reason=reason,
    )

    clear_position()
    current_position = None
    return True


def manage_trade(price, option_mark=None, option_bid=None):
    """
    Manage open trade with intelligent trailing stop losses based on option value.
    
    Trailing Stop Loss Strategy (based on option value, not SPY):
    - Entry (0% profit):     Stop = 5% below entry price
    - Up 2% profit:          Stop = 3% below entry price
    - Up 4% profit:          Stop = Trails 3% below current price
    - Up 5% profit:          Stop = Trails 2% below current price
    - Up 6% profit:          Stop = Trails 1% below current price
    
    Args:
        price: Current SPY price
        option_mark: Current option mark price
        option_bid: Current option bid price (used for exit)
    """
    global current_position

    persisted = load_position(Position)
    if persisted is not None:
        current_position = persisted

    if current_position is None:
        return

    # ==========================================
    # Check for market close conditions
    # ==========================================
    now_et = datetime.now(EASTERN_TZ)
    if now_et.time() >= dt_time(15, 59):
        print("END OF DAY EXIT: closing position at 3:59 PM ET")
        close_trade(price, "END_OF_DAY_EXIT", option_mark)
        return

    if datetime.now(EASTERN_TZ) - current_position.opened >= timedelta(minutes=15):
        print("MAX HOLD REACHED: closing position after 15 minutes")
        close_trade(price, "MAX_HOLD_15_MIN", option_mark)
        return

    # ==========================================
    # Validate option data
    # ==========================================
    if option_mark is None or option_mark <= 0:
        print("Waiting for valid option price to manage trade")
        return

    option_entry = float(current_position.option_entry or 0)

    if option_entry <= 0:
        print("Cannot manage trade: option entry price is missing")
        return

    # ==========================================
    # STEP 1: Initialize trailing stop if not set
    # ==========================================
    if getattr(current_position, "option_stop", 0) <= 0:
        initial_stop_value = option_entry * (1 + INITIAL_STOP_LOSS_PCT / 100)  # 5% below entry
        current_position.option_stop = initial_stop_value
        current_position.option_initial_stop = initial_stop_value
        print(f"[INIT] First candle: Setting initial stop to 5% below entry: ${initial_stop_value:.2f}")

    # ==========================================
    # STEP 2: Calculate profit and update trailing stop
    # ==========================================
    option_pnl_pct = ((option_mark - option_entry) / option_entry) * 100
    
    print(f"[TRAILING STOP] Profit: {option_pnl_pct:.2f}%")
    
    new_stop = current_position.option_stop
    
    if option_pnl_pct >= TRAIL_1_TRIGGER_PCT:  # Up 8%
        # Trail 1% below current price
        new_stop = option_mark * 0.99
        stop_type = "Trail 1%"
    elif option_pnl_pct >= TRAIL_2_TRIGGER_PCT:  # Up 7%
        # Trail 1.5% below current price
        new_stop = option_mark * 0.985
        stop_type = "Trail 1.5%"
    elif option_pnl_pct >= TRAIL_3_TRIGGER_PCT:  # Up 6%
        # Trail 2% below current price
        new_stop = option_mark * 0.98
        stop_type = "Trail 2%"
    elif option_pnl_pct >= TRAIL_4_TRIGGER_PCT:  # Up 5%
        # Trail 2.5% below current price
        new_stop = option_mark * 0.975
        stop_type = "Trail 2.5%"
    elif option_pnl_pct >= TRAIL_5_TRIGGER_PCT:  # Up 4%
        # Trail 3% below current price
        new_stop = option_mark * 0.97
        stop_type = "Trail 3%"
    elif option_pnl_pct >= THREE_PCT_TRIGGER_PCT:  # Up 3%
        # Set stop to 1% below entry
        new_stop = option_entry * (1 - (THREE_PCT_ENTRY_STOP_PCT / 100))
        stop_type = "3% Entry Lock"
    elif option_pnl_pct >= TWO_PCT_TRIGGER_PCT:  # Up 2%
        # Set stop to 3% below entry
        new_stop = option_entry * (1 - (TWO_PCT_ENTRY_STOP_PCT / 100))
        stop_type = "2% Entry Lock"
    else:
        # Below 2%: Keep 5% initial stop
        new_stop = current_position.option_initial_stop
        stop_type = "Initial 5%"
    
    # Only move stop higher, never lower (ratcheting stops)
    if new_stop > current_position.option_stop:
        current_position.option_stop = new_stop
        print(f"✓ UPDATED: {stop_type} → Stop: ${new_stop:.2f}")
    else:
        print(f"[STOP] Current: ${current_position.option_stop:.2f} | {stop_type}: ${new_stop:.2f}")

    save_position(current_position)

    print(
        f"OPTION MANAGEMENT | "
        f"Entry=${option_entry:.2f} | "
        f"Current=${option_mark:.2f} | "
        f"PnL={option_pnl_pct:.2f}% | "
        f"Stop=${current_position.option_stop:.2f} | "
        f"Status={stop_type}"
    )

    # ==========================================
    # STEP 3: Check if stop loss is hit
    # ==========================================
    stop_execution_price = (
        option_bid
        if option_bid is not None and option_bid > 0
        else option_mark
    )

    if stop_execution_price <= current_position.option_stop:
        # Determine if this is initial stop or trailing stop
        initial_stop = getattr(current_position, "option_initial_stop", current_position.option_stop)
        
        # TRAILING_STOP if: stop has moved (is higher than initial) AND trade is profitable
        if current_position.option_stop > initial_stop and option_pnl_pct > 0:
            exit_reason = "TRAILING_STOP"
        else:
            exit_reason = "OPTION_STOP"
        
        print(f"❌ STOP HIT: {exit_reason}")
        print(f"   Price: ${stop_execution_price:.2f} | Stop: ${current_position.option_stop:.2f}")
        close_trade(price, exit_reason, stop_execution_price)
        return

    # No fixed profit ceiling; dynamic trailing stop manages winners.
