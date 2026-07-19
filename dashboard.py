from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "mcleod_alpha.db"
POSITION_FILE = ROOT / "data" / "open_position.json"
SIGNALS_FILE = ROOT / "logs" / "signals.csv"


def load_current_position():
    if not POSITION_FILE.exists():
        return None

    try:
        return json.loads(POSITION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_latest_signal():
    if not SIGNALS_FILE.exists():
        return None

    try:
        with SIGNALS_FILE.open("r", newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return None

    if not rows:
        return None

    return rows[-1]


def load_trade_stats():
    if not DB.exists():
        return [], 0, 0.0

    with sqlite3.connect(DB) as con:
        cur = con.cursor()

        cur.execute(
            """
            SELECT entry_time, direction, entry_price, exit_price, pnl, exit_reason
            FROM trade_log
            ORDER BY id DESC
            LIMIT 20
            """
        )
        recent_trades = cur.fetchall()

        cur.execute(
            """
            SELECT COUNT(*)
            FROM trade_log
            WHERE date(entry_time) = date('now')
            """
        )
        today_count = cur.fetchone()[0] or 0

        cur.execute(
            """
            SELECT COALESCE(SUM(pnl), 0)
            FROM trade_log
            """
        )
        total_pnl = cur.fetchone()[0] or 0.0

    return recent_trades, int(today_count), float(total_pnl)


def render_dashboard():
    st.set_page_config(page_title="McLeod Alpha Dashboard", layout="wide")

    try:
        st.autorefresh(interval=10000)
    except Exception:
        pass

    st.title("McLeod Alpha Dashboard")
    st.caption("Auto-refreshing every 10 seconds")

    position = load_current_position()
    latest_signal = load_latest_signal()
    recent_trades, today_count, total_pnl = load_trade_stats()

    st.subheader("Current Position")
    if position is None:
        st.write("No open position")
    else:
        st.code(json.dumps(position, indent=2), language="json")

    st.subheader("Latest Signal")
    if latest_signal is None:
        st.write("No signal data.")
    else:
        st.code(json.dumps(latest_signal, indent=2, default=str), language="json")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Today's Trade Count", today_count)
    with col2:
        st.metric("Total P&L", f"{total_pnl:.2f}")
    with col3:
        st.metric("Recent Trades", len(recent_trades))

    st.subheader("Recent Trades")
    if not recent_trades:
        st.write("No completed trades.")
    else:
        trade_lines = [
            f"{index}. {entry_time} | {direction} | entry={entry_price} | exit={exit_price} | pnl={pnl} | reason={exit_reason}"
            for index, (entry_time, direction, entry_price, exit_price, pnl, exit_reason) in enumerate(
                recent_trades, start=1
            )
        ]
        st.code("\n".join(trade_lines), language="text")


if __name__ == "__main__":
    render_dashboard()