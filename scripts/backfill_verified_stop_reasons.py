#!/usr/bin/env python3
"""Apply only stop tiers proven by the retained live execution log."""

import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "mcleod_alpha.db"

# Each row is tied to its exact broker entry order and a retained log event.
VERIFIED_REASONS = {
    "1007246447574": "3% Stop",  # 10:54 PUT: stop ratcheted to $6.02.
    "1007249929028": "4% TRAIL",  # 11:54 CALL: stop ratcheted to $5.98.
}


def main():
    updated = 0
    with sqlite3.connect(DB_PATH) as connection:
        for entry_order_id, reason in VERIFIED_REASONS.items():
            cursor = connection.execute(
                """UPDATE trade_log
                   SET exit_reason = ?
                   WHERE broker_entry_order_id = ?
                     AND exit_reason = 'STOP'""",
                (reason, entry_order_id),
            )
            updated += cursor.rowcount
    print(f"Backfilled {updated} log-verified stop reason(s).")


if __name__ == "__main__":
    main()