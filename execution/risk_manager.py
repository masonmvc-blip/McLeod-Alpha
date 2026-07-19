from datetime import datetime

from datetime import timedelta

COOLDOWN_MINUTES_AFTER_STOP = 5
last_stop_time = None

MAX_TRADES_PER_DAY = 10
MAX_DAILY_LOSS = 1000.0

daily_trades = 0
daily_pnl = 0.0
current_day = datetime.now().date()


def reset_if_new_day():
    global current_day, daily_trades, daily_pnl

    today = datetime.now().date()

    if today != current_day:
        current_day = today
        daily_trades = 0
        daily_pnl = 0.0


def can_open_trade():
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


def record_trade(pnl):
    global daily_trades, daily_pnl

    daily_trades += 1
    daily_pnl += pnl
    
def record_stop():
    global last_stop_time
    last_stop_time = datetime.now()