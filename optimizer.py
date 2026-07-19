import sqlite3
from pathlib import Path
from collections import defaultdict

DB = Path("data/mcleod_alpha.db")


def trades():
    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM trade_log")]


def group(rows, field):
    d = defaultdict(list)
    for r in rows:
        d[str(r.get(field, "UNKNOWN"))].append(r)
    return d


def stats(rows):
    n = len(rows)
    if n == 0:
        return None

    pnl = [float(r["pnl"]) for r in rows]

    wins = sum(1 for p in pnl if p > 0)
    losses = sum(1 for p in pnl if p <= 0)

    return {
        "trades": n,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / n * 100,
        "total": sum(pnl),
        "average": sum(pnl) / n,
    }


def print_group(title, groups):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)

    for key in sorted(groups.keys()):
        s = stats(groups[key])
        if not s:
            continue

        print(
            f"{key:15} | "
            f"Trades {s['trades']:3d} | "
            f"Win {s['win_rate']:5.1f}% | "
            f"Avg {s['average']:7.3f} | "
            f"Total {s['total']:8.3f}"
        )


def main():
    rows = trades()

    if not rows:
        print("No trades found.")
        return

    print_group("BY DIRECTION", group(rows, "direction"))
    print_group("BY EXIT REASON", group(rows, "exit_reason"))
    print_group("BY OPTION DELTA", group(rows, "option_delta"))
    print_group("BY MARKET REGIME", group(rows, "regime"))


if __name__ == "__main__":
    main()