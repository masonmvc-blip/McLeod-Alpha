from __future__ import annotations

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cockpit
from engine.memory import get_memory

OUT_CSV = ROOT / "reports" / "broker_only_daily_pnl.csv"
OUT_MD = ROOT / "reports" / "broker_only_daily_pnl_summary.md"


@dataclass
class DayStats:
    all_rows: int = 0
    all_pnl: float = 0.0
    broker_rows: int = 0
    broker_pnl: float = 0.0
    unlinked_rows: int = 0
    unlinked_pnl: float = 0.0
    broker_wins: int = 0
    broker_losses: int = 0
    schwab_cash_pnl: float | None = None


def _as_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _has_text(value) -> bool:
    return value is not None and str(value).strip() != ""


def _is_broker_backed(row: dict) -> bool:
    """Classify rows as broker-backed only when entry+exit IDs are present.

    This is intentionally strict so daily performance reflects confirmed
    broker-tracked round trips, not synthetic or partially linked rows.
    """

    return (
        _has_text(row["broker_entry_order_id"])
        and _has_text(row["broker_exit_order_id"])
        and _has_text(row["option_symbol"])
    )


def _schwab_cash_day_pnl(day: str) -> float | None:
    """Return net SPY option cash P&L for a day from Schwab transaction source.

    This reuses cockpit's cash-basis helper so reconciliation aligns with
    the dashboard's broker net calculations.
    """

    try:
        value = cockpit._schwab_transaction_day_net_pnl(str(day))
        if value is None:
            return None
        return round(float(value), 2)
    except Exception:
        return None


def build_report() -> tuple[Path, Path, dict[str, DayStats]]:
    rows = get_memory().load_broker_daily_pnl_rows()

    daily: dict[str, DayStats] = defaultdict(DayStats)

    for row in rows:
        day = str(row["trade_date"])
        pnl = _as_float(row["pnl_dollars"], 0.0)
        item = daily[day]
        item.all_rows += 1
        item.all_pnl += pnl

        if _is_broker_backed(row):
            item.broker_rows += 1
            item.broker_pnl += pnl
            if pnl > 0:
                item.broker_wins += 1
            else:
                item.broker_losses += 1
        else:
            item.unlinked_rows += 1
            item.unlinked_pnl += pnl

    csv_fields = ["date", "all_rows", "all_pnl", "broker_rows", "broker_pnl", "broker_win_rate", "unlinked_rows", "unlinked_pnl", "broker_share_of_rows", "schwab_cash_pnl", "cash_minus_broker_logged"]
    csv_rows = []
    for day in sorted(daily.keys()):
        s = daily[day]
        s.schwab_cash_pnl = _schwab_cash_day_pnl(day)
        broker_win_rate = (s.broker_wins / s.broker_rows) if s.broker_rows > 0 else 0.0
        broker_share_rows = (s.broker_rows / s.all_rows) if s.all_rows > 0 else 0.0
        cash_minus_broker = round(float(s.schwab_cash_pnl) - float(s.broker_pnl), 2) if s.schwab_cash_pnl is not None else ""
        csv_rows.append({"date": day, "all_rows": s.all_rows, "all_pnl": round(s.all_pnl, 2), "broker_rows": s.broker_rows, "broker_pnl": round(s.broker_pnl, 2), "broker_win_rate": round(broker_win_rate, 4), "unlinked_rows": s.unlinked_rows, "unlinked_pnl": round(s.unlinked_pnl, 2), "broker_share_of_rows": round(broker_share_rows, 4), "schwab_cash_pnl": "" if s.schwab_cash_pnl is None else round(s.schwab_cash_pnl, 2), "cash_minus_broker_logged": cash_minus_broker})
    get_memory().write_report_csv(OUT_CSV, csv_fields, csv_rows, "broker_only_daily_pnl", source="broker_only_daily_pnl_report")

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Broker-Only Daily PnL",
        "",
        f"Generated: {generated_at}",
        "",
        "Rows are classified as broker-backed only when both `broker_entry_order_id` and `broker_exit_order_id` are present and `option_symbol` is populated.",
        "Schwab cash columns are net transaction cash flow (source-of-truth for account cash movement).",
        "",
        "| Date | All Rows | All PnL | Broker Rows | Broker PnL | Broker Win Rate | Unlinked Rows | Unlinked PnL | Schwab Cash PnL | Cash-Broker Variance |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for day in sorted(daily.keys()):
        s = daily[day]
        schwab_cash = _schwab_cash_day_pnl(day)
        s.schwab_cash_pnl = schwab_cash
        broker_win_rate = (
            (s.broker_wins / s.broker_rows) if s.broker_rows > 0 else 0.0
        )
        variance = (
            f"{(float(schwab_cash) - float(s.broker_pnl)):.2f}"
            if schwab_cash is not None
            else "N/A"
        )
        schwab_cash_text = f"{float(schwab_cash):.2f}" if schwab_cash is not None else "N/A"
        lines.append(
            "| "
            f"{day} | {s.all_rows} | {s.all_pnl:.2f} | {s.broker_rows} | {s.broker_pnl:.2f} | {broker_win_rate:.1%} | {s.unlinked_rows} | {s.unlinked_pnl:.2f} | {schwab_cash_text} | {variance}"
            " |"
        )

    get_memory().write_report_text(OUT_MD, "\n".join(lines) + "\n", "broker_only_daily_pnl", source="broker_only_daily_pnl_report")
    return OUT_CSV, OUT_MD, daily


def main() -> None:
    out_csv, out_md, daily = build_report()
    print(f"Wrote: {out_csv}")
    print(f"Wrote: {out_md}")
    if daily:
        latest = sorted(daily.keys())[-1]
        s = daily[latest]
        print(
            f"Latest day {latest}: all_pnl={s.all_pnl:.2f}, broker_pnl={s.broker_pnl:.2f}, "
            f"unlinked_pnl={s.unlinked_pnl:.2f}, broker_rows={s.broker_rows}, all_rows={s.all_rows}"
        )


if __name__ == "__main__":
    main()
