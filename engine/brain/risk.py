"""Canonical live trade-risk gate and its in-process state."""

from datetime import datetime, timedelta


COOLDOWN_MINUTES_AFTER_STOP = 5
MAX_TRADES_PER_DAY = 10
MAX_DAILY_LOSS = 1000.0

last_stop_time = None
daily_trades = 0
daily_pnl = 0.0
current_day = datetime.now().date()


def reset_if_new_day() -> None:
    """Reset daily risk counters when the local trading day changes."""
    global current_day, daily_trades, daily_pnl
    today = datetime.now().date()
    if today != current_day:
        current_day = today
        daily_trades = 0
        daily_pnl = 0.0


def can_open_trade() -> tuple[bool, str]:
    """Return whether the canonical risk gate allows another live entry."""
    reset_if_new_day()
    if last_stop_time is not None:
        cooldown_until = last_stop_time + timedelta(minutes=COOLDOWN_MINUTES_AFTER_STOP)
        if datetime.now() < cooldown_until:
            return False, "Stop-loss cooldown active"
    if daily_trades >= MAX_TRADES_PER_DAY:
        return False, "Max trades reached"
    if daily_pnl <= -MAX_DAILY_LOSS:
        return False, "ABSOLUTE STOP: Daily loss limit reached ($1,000)"
    return True, ""


def record_trade(pnl: float) -> None:
    """Record a completed trade for the canonical daily risk gate."""
    global daily_trades, daily_pnl
    daily_trades += 1
    daily_pnl += float(pnl)


def record_stop() -> None:
    """Start the canonical post-stop cooldown."""
    global last_stop_time
    last_stop_time = datetime.now()