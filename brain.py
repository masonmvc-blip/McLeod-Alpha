import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/mcleod_alpha.db")
DB_PATH.parent.mkdir(exist_ok=True)

def connect():
    return sqlite3.connect(DB_PATH)

def init_db():
    with connect() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            price REAL,
            market_regime TEXT,
            call_score INTEGER,
            put_score INTEGER,
            call_pushes INTEGER,
            put_pushes INTEGER,
            ema10 REAL,
            ema20 REAL,
            ema50 REAL,
            vwap REAL,
            macd_hist REAL,
            decision TEXT
        )
        """)
        con.commit()

def classify_market(last, prev):
    spread = abs(last.ema10 - last.ema50)

    if last.close > last.vwap and last.ema10 > last.ema20 > last.ema50 and last.ema10 > prev.ema10:
        return "BULL_TREND"
    if last.close < last.vwap and last.ema10 < last.ema20 < last.ema50 and last.ema10 < prev.ema10:
        return "BEAR_TREND"
    if spread < 0.15:
        return "CHOP"
    return "TRANSITION"

def log_signal(row):
    init_db()
    with connect() as con:
        con.execute("""
        INSERT INTO signals (
            timestamp, symbol, price, market_regime,
            call_score, put_score, call_pushes, put_pushes,
            ema10, ema20, ema50, vwap, macd_hist, decision
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["timestamp"], row["symbol"], row["price"], row["market_regime"],
            row["call_score"], row["put_score"], row["call_pushes"], row["put_pushes"],
            row["ema10"], row["ema20"], row["ema50"], row["vwap"],
            row["macd_hist"], row["decision"]
        ))
        con.commit()
