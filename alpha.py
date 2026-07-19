import argparse
from html import parser
from operator import sub
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "data" / "mcleod_alpha.db"
ACTIVE_MONITOR = ROOT / "phase3_monitor.py"


def command_status(args):
    monitor = ACTIVE_MONITOR

    print("\n========== MCLEOD ALPHA ==========\n")

    print(f"Monitor: {'FOUND' if monitor.exists() else 'MISSING'}")

    if DB.exists():
        print("Database: OK")
    else:
        print("Database: NOT FOUND")

    try:
        con = sqlite3.connect(DB)
        cur = con.cursor()

        cur.execute("SELECT COUNT(*) FROM trade_log")
        trades = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM trade_log
            WHERE date(entry_time)=date('now')
        """)
        today = cur.fetchone()[0]

        print(f"Trades Logged: {trades}")
        print(f"Today's Trades: {today}")

        con.close()

    except Exception as e:
        print(f"Database Error: {e}")

    print("\n===============================\n")


def command_trades(args):
    con = sqlite3.connect(DB)
    cur = con.cursor()

    print()

    for row in cur.execute("""
        SELECT
            entry_time,
            direction,
            entry_price,
            exit_price,
            pnl,
            exit_reason
        FROM trade_log
        ORDER BY id DESC
        LIMIT 20
    """):
        print(row)

    con.close()


def command_position(args):
    pos = ROOT / "data" / "open_position.json"

    if pos.exists():
        print(pos.read_text())
    else:
        print("No open position.")


def command_reset(args):
    pos = ROOT / "data" / "open_position.json"

    if pos.exists():
        pos.unlink()

    print("Position reset.")


def command_start(args):
    monitor = ACTIVE_MONITOR

    subprocess.run([sys.executable, str(monitor)])


def main():

    parser = argparse.ArgumentParser()

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status")
    sub.add_parser("trades")
    sub.add_parser("position")
    sub.add_parser("reset")
    sub.add_parser("start")
    sub.add_parser("health")
    sub.add_parser("preflight")
    sub.add_parser("learn")
    sub.add_parser("optimize")
    sub.add_parser("validate")
    sub.add_parser("backtest")

    args = parser.parse_args()

    if args.command == "status":
        command_status(args)

    elif args.command == "trades":
        command_trades(args)

    elif args.command == "position":
        command_position(args)

    elif args.command == "reset":
        command_reset(args)

    elif args.command == "start":
        command_start(args)

    elif args.command == "health":
        import health
        health.main()

    elif args.command == "preflight":
        import preflight
        preflight.main()

    elif args.command == "learn":
        import learning_engine
        learning_engine.main()

    elif args.command == "optimize":
        import optimizer
        optimizer.main()

    elif args.command == "validate":
        import validation
        validation.main()

    elif args.command == "backtest":
        import reports.backtester as backtester
        backtester.main()

    else:
        parser.print_help()

if __name__ == "__main__":
    main()