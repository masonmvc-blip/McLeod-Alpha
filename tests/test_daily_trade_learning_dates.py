import sqlite3

from run_daily_trade_learning import _load_day_rows, _resolve_target_date


def _connection():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE trade_log (
            id INTEGER PRIMARY KEY,
            entry_time TEXT,
            exit_time TEXT,
            direction TEXT,
            exit_reason TEXT,
            pnl REAL,
            option_pnl_dollars REAL,
            option_symbol TEXT,
            broker_entry_order_id TEXT,
            broker_exit_order_id TEXT
        )
        """
    )
    return con


def test_daily_learning_accepts_schwab_compact_utc_offsets():
    con = _connection()
    con.executemany(
        """
        INSERT INTO trade_log (
            id, entry_time, exit_time, direction, exit_reason, pnl,
            option_pnl_dollars, option_symbol,
            broker_entry_order_id, broker_exit_order_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                "2026-07-28T09:43:15-04:00",
                "2026-07-28T09:48:40-04:00",
                "PUT",
                "MANUAL_EXIT_LIMIT",
                -34.09,
                -34.09,
                "SPY PUT",
                "entry-1",
                "exit-1",
            ),
            (
                2,
                "2026-07-28T14:49:03+0000",
                "2026-07-28T14:52:17+0000",
                "CALL",
                "3% Stop",
                51.92,
                51.92,
                "SPY CALL",
                "entry-2",
                "exit-2",
            ),
        ],
    )

    assert _resolve_target_date(con, None) == "2026-07-28"
    assert [row["id"] for row in _load_day_rows(con, "2026-07-28")] == [1, 2]
