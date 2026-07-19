from pathlib import Path
import sqlite3

DB = Path("data/mcleod_alpha.db")
POSITION = Path("position_store.json")
SIGNALS = Path("logs/signals.csv")
REPORTS = Path("reports")


def check(label, passed):
    print(f"[{'PASS' if passed else 'FAIL'}] {label}")


def db_exists():
    return DB.exists()


def trade_table_exists():
    if not DB.exists():
        return False
    try:
        con = sqlite3.connect(DB)
        cur = con.cursor()
        cur.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            AND name='trade_log'
        """)
        ok = cur.fetchone() is not None
        con.close()
        return ok
    except Exception:
        return False


def main():
    results = [
        ("SQLite database", db_exists()),
        ("trade_log table", trade_table_exists()),
        ("position_store.json", POSITION.exists()),
        ("logs/signals.csv", SIGNALS.exists()),
        ("reports folder", REPORTS.exists()),
    ]

    print("\nMcLeod Alpha Health Check\n")

    for label, passed in results:
        check(label, passed)

    if all(passed for _, passed in results):
        print("\nREADY")
        return 0

    print("\nBLOCKED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())