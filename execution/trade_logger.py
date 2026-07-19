import sqlite3
from pathlib import Path
from datetime import datetime

DB = Path("data/mcleod_alpha.db")

def init_trade_log():
    with sqlite3.connect(DB) as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_time TEXT,
            exit_time TEXT,
            direction TEXT,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            exit_reason TEXT,
            feature_payload TEXT
        )
        """)
        columns = [row[1] for row in con.execute("PRAGMA table_info(trade_log)").fetchall()]
        if "feature_payload" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN feature_payload TEXT")
        if "option_symbol" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN option_symbol TEXT")
        if "option_entry" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN option_entry REAL")
        if "option_exit" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN option_exit REAL")
        if "option_quantity" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN option_quantity INTEGER")
        if "option_delta" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN option_delta REAL")
        if "option_return" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN option_return REAL")
        if "option_pnl_dollars" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN option_pnl_dollars REAL")
        if "option_pnl_pct" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN option_pnl_pct REAL")
        if "broker_entry_order_id" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN broker_entry_order_id TEXT")
        if "broker_exit_order_id" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN broker_exit_order_id TEXT")
        if "momentum_freshness_score" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN momentum_freshness_score REAL")
        if "momentum_phase" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN momentum_phase TEXT")
        if "entry_diagnostic_snapshot" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN entry_diagnostic_snapshot TEXT")
        if "exit_diagnostic_snapshot" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN exit_diagnostic_snapshot TEXT")
        if "absorption_score" not in columns:
            con.execute("ALTER TABLE trade_log ADD COLUMN absorption_score REAL")

        con.execute("""
        CREATE TABLE IF NOT EXISTS bot_order_audit (
            order_id TEXT PRIMARY KEY,
            intent TEXT,
            created_at TEXT
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS trade_diagnostic_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TEXT,
            event_type TEXT,
            direction TEXT,
            option_symbol TEXT,
            source TEXT,
            snapshot TEXT
        )
        """)


def log_bot_order(order_id, intent):
    """Persist a bot-submitted broker order ID for exact source attribution."""
    order_id = str(order_id or "").strip()
    if not order_id:
        return

    init_trade_log()

    with sqlite3.connect(DB) as con:
        con.execute(
            """
            INSERT OR REPLACE INTO bot_order_audit (order_id, intent, created_at)
            VALUES (?, ?, ?)
            """,
            (order_id, str(intent or ""), datetime.utcnow().isoformat()),
        )


def log_trade_diagnostic_event(event_type, direction, option_symbol=None, source=None, snapshot=None):
    """Persist point-in-time diagnostic snapshots at ENTRY and EXIT."""
    init_trade_log()
    with sqlite3.connect(DB) as con:
        con.execute(
            """
            INSERT INTO trade_diagnostic_events (
                event_time,
                event_type,
                direction,
                option_symbol,
                source,
                snapshot
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(),
                str(event_type or ""),
                str(direction or ""),
                str(option_symbol or ""),
                str(source or ""),
                snapshot,
            ),
        )

def log_trade(entry_time,
              exit_time,
              direction,
              entry_price,
              exit_price,
              pnl,
              exit_reason,
              feature_payload=None,
              option_symbol=None,
              option_entry=None,
              option_exit=None,
              option_quantity=None,
              option_delta=None,
              option_return=None,
              option_pnl_dollars=None,
              option_pnl_pct=None,
              broker_entry_order_id=None,
              broker_exit_order_id=None,
              momentum_freshness_score=None,
              momentum_phase=None,
              absorption_score=None,
              entry_diagnostic_snapshot=None,
              exit_diagnostic_snapshot=None):

    init_trade_log()

    with sqlite3.connect(DB) as con:
        con.execute("""
        INSERT INTO trade_log (
            entry_time,
            exit_time,
            direction,
            entry_price,
            exit_price,
            pnl,
            exit_reason,
            feature_payload,
            option_symbol,
            option_entry,
            option_exit,
            option_quantity,
            option_delta,
            option_return,
            option_pnl_dollars,
            option_pnl_pct,
            broker_entry_order_id,
            broker_exit_order_id,
            momentum_freshness_score,
            momentum_phase,
            absorption_score,
            entry_diagnostic_snapshot,
            exit_diagnostic_snapshot
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry_time,
            exit_time,
            direction,
            entry_price,
            exit_price,
            pnl,
            exit_reason,
            feature_payload,
            option_symbol,
            option_entry,
            option_exit,
            option_quantity,
            option_delta,
            option_return,
            option_pnl_dollars,
            option_pnl_pct,
            broker_entry_order_id,
            broker_exit_order_id,
            momentum_freshness_score,
            momentum_phase,
            absorption_score,
            entry_diagnostic_snapshot,
            exit_diagnostic_snapshot,
        ))
        