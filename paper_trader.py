from datetime import datetime
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
from execution.sms_alerts import send_trade_entry_alert, send_trade_exit_alert

DB = Path("data/mcleod_alpha.db")
DB.parent.mkdir(exist_ok=True)

TARGET_PCT = 0.05
STOP_PCT = -0.05
MAX_TRADES_PER_DAY = 2
EASTERN_TZ = ZoneInfo("America/New_York")

def init():
    with sqlite3.connect(DB) as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_time TEXT,
            exit_time TEXT,
            symbol TEXT,
            direction TEXT,
            entry_price REAL,
            exit_price REAL,
            pnl_pct REAL,
            status TEXT,
            entry_reason TEXT,
            exit_reason TEXT
        )
        """)

def open_trades():
    with sqlite3.connect(DB) as con:
        return con.execute("SELECT * FROM paper_trades WHERE status='OPEN'").fetchall()

def trades_today():
    today = datetime.now(EASTERN_TZ).strftime("%Y-%m-%d")
    with sqlite3.connect(DB) as con:
        return con.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE entry_time LIKE ?",
            (today + "%",)
        ).fetchone()[0]

def enter_trade(symbol, direction, price, reason):
    init()
    if trades_today() >= MAX_TRADES_PER_DAY:
        print("Paper trade skipped: max trades reached.")
        return
    if open_trades():
        print("Paper trade skipped: already in trade.")
        return

    with sqlite3.connect(DB) as con:
        con.execute("""
        INSERT INTO paper_trades
        (entry_time, symbol, direction, entry_price, status, entry_reason)
        VALUES (?, ?, ?, ?, 'OPEN', ?)
        """, (datetime.now(EASTERN_TZ).isoformat(timespec="seconds"), symbol, direction, price, reason))

    print(f"PAPER ENTRY: {direction} {symbol} at {price}")
    send_trade_entry_alert(
        mode="PAPER",
        direction=direction,
        quantity=1,
        option_symbol=symbol,
        option_entry=float(price or 0.0),
        spy_entry=0.0,
        reason=reason,
    )

def update_trade(current_price):
    init()
    trades = open_trades()
    if not trades:
        return

    trade = trades[0]
    trade_id = trade[0]
    direction = trade[3]
    entry_price = trade[4]

    if direction == "CALL":
        pnl_pct = (current_price - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - current_price) / entry_price

    if pnl_pct >= TARGET_PCT:
        exit_reason = "TARGET_5_PERCENT"
    elif pnl_pct <= STOP_PCT:
        exit_reason = "STOP_5_PERCENT"
    else:
        print(f"Paper trade open. P/L: {pnl_pct:.2%}")
        return

    with sqlite3.connect(DB) as con:
        con.execute("""
        UPDATE paper_trades
        SET exit_time=?, exit_price=?, pnl_pct=?, status='CLOSED', exit_reason=?
        WHERE id=?
        """, (
            datetime.now(EASTERN_TZ).isoformat(timespec="seconds"),
            current_price,
            pnl_pct,
            exit_reason,
            trade_id
        ))

    print(f"PAPER EXIT: {exit_reason} at {current_price} | P/L {pnl_pct:.2%}")
    send_trade_exit_alert(
        mode="PAPER",
        direction=direction,
        quantity=1,
        option_symbol=trade[2],
        option_entry=float(entry_price or 0.0),
        option_exit=float(current_price or 0.0),
        pnl_dollars=0.0,
        pnl_pct=float(pnl_pct * 100.0),
        exit_reason=exit_reason,
    )

if __name__ == "__main__":
    init()
    print("Paper trader ready.")
