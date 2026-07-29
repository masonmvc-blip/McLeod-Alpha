#!/usr/bin/env python3
"""Backfill evidence-honest Day Trade SPY shadow reports for committed trades."""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reports.day_trade_spy_shadow_report import write_day_trade_spy_shadow_report


def _trade_dates(root: Path) -> list[str]:
    db_path = root / "data" / "mcleod_alpha.db"
    if not db_path.exists() or not db_path.stat().st_size:
        return []
    with sqlite3.connect(str(db_path)) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trade_log'"
        ).fetchone()
        if not exists:
            return []
        rows = connection.execute(
            """
            SELECT DISTINCT substr(entry_time, 1, 10)
            FROM trade_log
            WHERE entry_time IS NOT NULL
              AND substr(entry_time, 1, 10) GLOB '????-??-??'
              AND trim(COALESCE(broker_entry_order_id, '')) <> ''
              AND trim(COALESCE(broker_exit_order_id, '')) <> ''
            ORDER BY 1
            """
        ).fetchall()
    return [str(row[0]) for row in rows]


def backfill(*, root: Path = ROOT, dates: list[str] | None = None) -> int:
    selected = dates if dates is not None else _trade_dates(root)
    for trading_date in selected:
        payload, json_path, _, _ = write_day_trade_spy_shadow_report(
            trading_date, root=root
        )
        print(
            f"{trading_date}: {payload['sample_size']} broker-backed trades; "
            f"{payload['evaluated_opportunities']} opportunities -> {json_path}"
        )
    return len(selected)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill Day Trade SPY shadow reports without changing live behavior"
    )
    parser.add_argument("--date", action="append", dest="dates", help="YYYY-MM-DD; repeatable")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    count = backfill(root=args.root.resolve(), dates=args.dates)
    print(f"Completed {count} trading date(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
