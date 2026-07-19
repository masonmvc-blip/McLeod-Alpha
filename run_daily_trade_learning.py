#!/usr/bin/env python3
"""Daily trade-learning workflow for live McLeod Alpha performance.

This runner analyzes the latest trading day in trade_log, writes a daily
learning report, and runs model evaluator/optimizer so improvements compound
without manual intervention.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from engine.model_evaluator import run_model_evaluator
from engine.weight_optimizer import run_weight_optimizer


WORKSPACE = Path(__file__).parent
DATA_DIR = WORKSPACE / "data"
REPORTS_DIR = WORKSPACE / "reports"
LEARNING_DIR = REPORTS_DIR / "daily_trade_learning"
DB_PATH = DATA_DIR / "mcleod_alpha.db"


@dataclass
class SliceStats:
    trades: int = 0
    pnl: float = 0.0
    wins: int = 0
    losses: int = 0

    @property
    def win_rate(self) -> float:
        return (self.wins / self.trades) if self.trades else 0.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _has_text(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _is_broker_backed(row: sqlite3.Row) -> bool:
    return (
        _has_text(row["broker_entry_order_id"])
        and _has_text(row["broker_exit_order_id"])
        and _has_text(row["option_symbol"])
    )


def _resolve_target_date(con: sqlite3.Connection, date_arg: str | None) -> str:
    if date_arg:
        return date_arg

    today = date.today().isoformat()
    row = con.execute(
        """
        SELECT date(entry_time) AS trade_date
        FROM trade_log
        WHERE entry_time IS NOT NULL
          AND date(entry_time) IS NOT NULL
          AND date(entry_time) <= ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (today,),
    ).fetchone()
    if not row or not row["trade_date"]:
        raise RuntimeError("No dated trades found in trade_log.")
    return str(row["trade_date"])


def _load_day_rows(con: sqlite3.Connection, trading_date: str) -> list[sqlite3.Row]:
    rows = con.execute(
        """
        SELECT
            id,
            entry_time,
            exit_time,
            direction,
            exit_reason,
            COALESCE(option_pnl_dollars, pnl, 0.0) AS pnl_dollars,
            option_symbol,
            broker_entry_order_id,
            broker_exit_order_id
        FROM trade_log
        WHERE date(entry_time) = ?
        ORDER BY entry_time, id
        """,
        (trading_date,),
    ).fetchall()
    return list(rows)


def _accumulate_stats(stats: SliceStats, pnl: float) -> None:
    stats.trades += 1
    stats.pnl += pnl
    if pnl > 0:
        stats.wins += 1
    else:
        stats.losses += 1


def _summarize_rows(rows: list[sqlite3.Row]) -> dict[str, Any]:
    overall = SliceStats()
    broker = SliceStats()
    unlinked = SliceStats()

    by_direction: dict[str, SliceStats] = {}
    by_exit: dict[str, SliceStats] = {}

    for row in rows:
        pnl = _safe_float(row["pnl_dollars"], 0.0)
        _accumulate_stats(overall, pnl)

        if _is_broker_backed(row):
            _accumulate_stats(broker, pnl)
        else:
            _accumulate_stats(unlinked, pnl)

        direction = str(row["direction"] or "UNKNOWN").upper()
        direction_stats = by_direction.setdefault(direction, SliceStats())
        _accumulate_stats(direction_stats, pnl)

        exit_reason = str(row["exit_reason"] or "UNKNOWN")
        exit_stats = by_exit.setdefault(exit_reason, SliceStats())
        _accumulate_stats(exit_stats, pnl)

    biggest_losses = sorted(rows, key=lambda r: _safe_float(r["pnl_dollars"], 0.0))[:5]
    biggest_wins = sorted(rows, key=lambda r: _safe_float(r["pnl_dollars"], 0.0), reverse=True)[:5]

    def _slice_to_dict(s: SliceStats) -> dict[str, Any]:
        return {
            "trades": s.trades,
            "pnl": round(s.pnl, 2),
            "wins": s.wins,
            "losses": s.losses,
            "win_rate": round(s.win_rate, 4),
        }

    return {
        "overall": _slice_to_dict(overall),
        "broker_backed": _slice_to_dict(broker),
        "unlinked": _slice_to_dict(unlinked),
        "by_direction": {k: _slice_to_dict(v) for k, v in sorted(by_direction.items())},
        "by_exit_reason": {k: _slice_to_dict(v) for k, v in sorted(by_exit.items())},
        "top_losses": [
            {
                "id": int(r["id"]),
                "entry_time": r["entry_time"],
                "direction": r["direction"],
                "exit_reason": r["exit_reason"],
                "pnl_dollars": round(_safe_float(r["pnl_dollars"], 0.0), 2),
                "broker_backed": _is_broker_backed(r),
            }
            for r in biggest_losses
        ],
        "top_wins": [
            {
                "id": int(r["id"]),
                "entry_time": r["entry_time"],
                "direction": r["direction"],
                "exit_reason": r["exit_reason"],
                "pnl_dollars": round(_safe_float(r["pnl_dollars"], 0.0), 2),
                "broker_backed": _is_broker_backed(r),
            }
            for r in biggest_wins
        ],
    }


def _build_actionable_lessons(summary: dict[str, Any]) -> list[dict[str, Any]]:
    lessons: list[dict[str, Any]] = []

    overall = summary.get("overall", {}) or {}
    broker = summary.get("broker_backed", {}) or {}
    unlinked = summary.get("unlinked", {}) or {}
    by_exit = summary.get("by_exit_reason", {}) or {}
    by_direction = summary.get("by_direction", {}) or {}

    overall_trades = int(overall.get("trades") or 0)
    overall_win_rate = float(overall.get("win_rate") or 0.0)
    broker_trades = int(broker.get("trades") or 0)
    broker_pnl = float(broker.get("pnl") or 0.0)
    unlinked_trades = int(unlinked.get("trades") or 0)
    unlinked_pnl = float(unlinked.get("pnl") or 0.0)

    if broker_trades > 0 and broker_pnl < 0:
        lessons.append(
            {
                "priority": "high",
                "theme": "live_risk",
                "title": "Broker-backed day finished negative",
                "signal": f"broker_pnl={broker_pnl:.2f} across {broker_trades} trades",
                "action": "Reduce early-session aggressiveness and require stricter confirmation on first two entries.",
            }
        )

    if unlinked_trades > 0 and abs(unlinked_pnl) >= max(25.0, abs(broker_pnl) * 0.5):
        lessons.append(
            {
                "priority": "high",
                "theme": "data_integrity",
                "title": "Unlinked rows materially move daily totals",
                "signal": f"unlinked_pnl={unlinked_pnl:.2f} across {unlinked_trades} rows",
                "action": "Audit trade linkage daily and treat broker-backed PnL as canonical for performance decisions.",
            }
        )

    worst_exit = None
    for reason, stats in by_exit.items():
        pnl = float((stats or {}).get("pnl") or 0.0)
        trades = int((stats or {}).get("trades") or 0)
        if trades <= 0:
            continue
        if worst_exit is None or pnl < worst_exit[1]:
            worst_exit = (str(reason), pnl, trades)
    if worst_exit is not None and worst_exit[1] < 0:
        lessons.append(
            {
                "priority": "medium",
                "theme": "exit_quality",
                "title": "Largest drag came from one exit bucket",
                "signal": f"{worst_exit[0]} pnl={worst_exit[1]:.2f} on {worst_exit[2]} trades",
                "action": "Review this exit bucket first during post-close replay and tighten invalidation conditions.",
            }
        )

    call_stats = by_direction.get("CALL") or {}
    put_stats = by_direction.get("PUT") or {}
    call_pnl = float(call_stats.get("pnl") or 0.0)
    put_pnl = float(put_stats.get("pnl") or 0.0)
    call_trades = int(call_stats.get("trades") or 0)
    put_trades = int(put_stats.get("trades") or 0)
    if call_trades > 0 and put_trades > 0 and abs(call_pnl - put_pnl) >= 40.0:
        stronger = "CALL" if call_pnl > put_pnl else "PUT"
        weaker = "PUT" if stronger == "CALL" else "CALL"
        lessons.append(
            {
                "priority": "medium",
                "theme": "direction_bias",
                "title": "Directional edge diverged",
                "signal": f"{stronger} outperformed {weaker} by {abs(call_pnl - put_pnl):.2f}",
                "action": f"Favor {stronger} setups until replay confirms {weaker} recovers consistency.",
            }
        )

    if overall_trades >= 4 and overall_win_rate < 0.45:
        lessons.append(
            {
                "priority": "medium",
                "theme": "entry_selectivity",
                "title": "Win rate below target band",
                "signal": f"overall_win_rate={overall_win_rate:.1%} on {overall_trades} trades",
                "action": "Increase selectivity by requiring cleaner momentum alignment before entry.",
            }
        )

    if not lessons:
        lessons.append(
            {
                "priority": "low",
                "theme": "stability",
                "title": "No major red flags detected",
                "signal": "Daily distribution is within normal range",
                "action": "Continue current risk process and monitor drift with weekly optimization outputs.",
            }
        )

    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(lessons, key=lambda x: priority_order.get(str(x.get("priority", "low")), 3))


def _build_scale_decision(
    summary: dict[str, Any],
    lessons: list[dict[str, Any]],
    evaluator_result: dict[str, Any],
    optimizer_result: dict[str, Any],
) -> dict[str, Any]:
    """Return next-session size guidance for +1 contract/day scaling.

    Decision meanings:
    - SCALE_UP: increase by 1 contract is allowed.
    - HOLD: keep the same contract size.
    - SCALE_DOWN: reduce by 1 contract.
    """

    overall = summary.get("overall", {}) or {}
    broker = summary.get("broker_backed", {}) or {}
    unlinked = summary.get("unlinked", {}) or {}
    by_exit = summary.get("by_exit_reason", {}) or {}

    overall_trades = int(overall.get("trades") or 0)
    overall_pnl = float(overall.get("pnl") or 0.0)
    overall_win_rate = float(overall.get("win_rate") or 0.0)
    broker_trades = int(broker.get("trades") or 0)
    broker_pnl = float(broker.get("pnl") or 0.0)
    unlinked_trades = int(unlinked.get("trades") or 0)
    unlinked_pnl = float(unlinked.get("pnl") or 0.0)

    stop_stats = by_exit.get("STOP") or by_exit.get("OPTION_STOP") or {}
    stop_pnl = float(stop_stats.get("pnl") or 0.0)

    high_priority_count = sum(1 for row in lessons if str(row.get("priority") or "").lower() == "high")

    opt_status = str(optimizer_result.get("status") or "unknown")
    eval_status = str(evaluator_result.get("status") or "ok")

    checks = [
        {
            "name": "sample_size",
            "passed": overall_trades >= 3,
            "detail": f"overall_trades={overall_trades}",
        },
        {
            "name": "win_rate_floor",
            "passed": (overall_trades < 3) or (overall_win_rate >= 0.45),
            "detail": f"overall_win_rate={overall_win_rate:.1%}",
        },
        {
            "name": "broker_backed_non_negative",
            "passed": (broker_trades == 0) or (broker_pnl >= 0),
            "detail": f"broker_trades={broker_trades}, broker_pnl={broker_pnl:.2f}",
        },
        {
            "name": "stop_loss_drag",
            "passed": stop_pnl > -75.0,
            "detail": f"stop_pnl={stop_pnl:.2f}",
        },
        {
            "name": "unlinked_distortion",
            "passed": (unlinked_trades == 0) or (abs(unlinked_pnl) < max(25.0, abs(overall_pnl) * 0.5)),
            "detail": f"unlinked_trades={unlinked_trades}, unlinked_pnl={unlinked_pnl:.2f}",
        },
        {
            "name": "no_high_priority_alerts",
            "passed": high_priority_count == 0,
            "detail": f"high_priority_alerts={high_priority_count}",
        },
        {
            "name": "learning_jobs_healthy",
            "passed": eval_status == "ok" and opt_status in {"ok", "insufficient_history", "insufficient_samples"},
            "detail": f"model_evaluator={eval_status}, weight_optimizer={opt_status}",
        },
    ]

    failed = [c for c in checks if not bool(c.get("passed"))]

    # Hard drawdown / execution-warning path: step down regardless of other checks.
    severe_loss = (broker_trades > 0 and broker_pnl <= -100.0) or (overall_pnl <= -150.0)
    if severe_loss:
        decision = "SCALE_DOWN"
        increase_allowed = False
        contract_step = -1
        rationale = "Severe daily loss threshold breached; reduce risk by 1 contract."
    elif failed:
        decision = "HOLD"
        increase_allowed = False
        contract_step = 0
        rationale = "One or more scale-up gates failed; keep size unchanged next session."
    else:
        decision = "SCALE_UP"
        increase_allowed = True
        contract_step = 1
        rationale = "All scale-up gates passed; increase by 1 contract next session."

    return {
        "decision": decision,
        "increase_allowed": increase_allowed,
        "contract_step": contract_step,
        "rationale": rationale,
        "checks": checks,
        "failed_checks": [c.get("name") for c in failed],
    }


def _write_daily_csv(path: Path, rows: list[sqlite3.Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "id",
            "entry_time",
            "exit_time",
            "direction",
            "exit_reason",
            "pnl_dollars",
            "option_symbol",
            "broker_entry_order_id",
            "broker_exit_order_id",
            "broker_backed",
        ])
        for r in rows:
            writer.writerow([
                r["id"],
                r["entry_time"],
                r["exit_time"],
                r["direction"],
                r["exit_reason"],
                round(_safe_float(r["pnl_dollars"], 0.0), 2),
                r["option_symbol"],
                r["broker_entry_order_id"],
                r["broker_exit_order_id"],
                int(_is_broker_backed(r)),
            ])


def _write_markdown(
    path: Path,
    trading_date: str,
    summary: dict[str, Any],
    evaluator: dict[str, Any],
    optimizer: dict[str, Any],
    lessons: list[dict[str, Any]],
    scale_decision: dict[str, Any],
) -> None:
    o = summary["overall"]
    b = summary["broker_backed"]
    u = summary["unlinked"]

    lines = [
        "# Daily Trade Learning Report",
        "",
        f"Date: {trading_date}",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Core Performance",
        "",
        "| Slice | Trades | PnL | Wins | Losses | Win Rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| Overall | {o['trades']} | {o['pnl']:.2f} | {o['wins']} | {o['losses']} | {o['win_rate']:.1%} |",
        f"| Broker-backed | {b['trades']} | {b['pnl']:.2f} | {b['wins']} | {b['losses']} | {b['win_rate']:.1%} |",
        f"| Unlinked | {u['trades']} | {u['pnl']:.2f} | {u['wins']} | {u['losses']} | {u['win_rate']:.1%} |",
        "",
        "## Exit Reason Breakdown",
        "",
        "| Exit Reason | Trades | PnL | Win Rate |",
        "| --- | ---: | ---: | ---: |",
    ]

    for reason, s in summary["by_exit_reason"].items():
        lines.append(f"| {reason} | {s['trades']} | {s['pnl']:.2f} | {s['win_rate']:.1%} |")

    lines.extend([
        "",
        "## Direction Breakdown",
        "",
        "| Direction | Trades | PnL | Win Rate |",
        "| --- | ---: | ---: | ---: |",
    ])

    for direction, s in summary["by_direction"].items():
        lines.append(f"| {direction} | {s['trades']} | {s['pnl']:.2f} | {s['win_rate']:.1%} |")

    lines.extend([
        "",
        "## Biggest Losses (Top 5)",
        "",
        "| ID | Entry Time | Direction | Exit Reason | PnL | Broker Backed |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ])

    for row in summary["top_losses"]:
        lines.append(
            f"| {row['id']} | {row['entry_time']} | {row['direction']} | {row['exit_reason']} | {row['pnl_dollars']:.2f} | {int(bool(row['broker_backed']))} |"
        )

    lines.extend([
        "",
        "## Biggest Wins (Top 5)",
        "",
        "| ID | Entry Time | Direction | Exit Reason | PnL | Broker Backed |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ])

    for row in summary["top_wins"]:
        lines.append(
            f"| {row['id']} | {row['entry_time']} | {row['direction']} | {row['exit_reason']} | {row['pnl_dollars']:.2f} | {int(bool(row['broker_backed']))} |"
        )

    lines.extend([
        "",
        "## Actionable Lessons",
        "",
    ])

    for lesson in lessons:
        priority = str(lesson.get("priority") or "low").upper()
        title = str(lesson.get("title") or "Untitled")
        signal = str(lesson.get("signal") or "")
        action = str(lesson.get("action") or "")
        lines.append(f"- [{priority}] {title} | Signal: {signal} | Action: {action}")

    decision = str(scale_decision.get("decision") or "HOLD")
    increase_allowed = bool(scale_decision.get("increase_allowed"))
    contract_step = int(scale_decision.get("contract_step") or 0)
    rationale = str(scale_decision.get("rationale") or "")

    lines.extend([
        "",
        "## Scale Decision (Next Session)",
        "",
        f"- increase_by_one_allowed: {'YES' if increase_allowed else 'NO'}",
        f"- decision: {decision}",
        f"- contract_step: {contract_step:+d}",
        f"- rationale: {rationale}",
        "",
        "### Scale Gate Checks",
        "",
    ])

    for check in scale_decision.get("checks", []):
        passed = bool(check.get("passed"))
        icon = "PASS" if passed else "FAIL"
        lines.append(f"- [{icon}] {check.get('name')}: {check.get('detail')}")

    lines.extend([
        "",
        "## Model Learning Jobs",
        "",
        f"- model_evaluator_status: {evaluator.get('status', 'unknown')}",
        f"- weight_optimizer_status: {optimizer.get('status', 'unknown')}",
        "",
    ])

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_daily_learning(target_date: str | None = None) -> int:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Trade DB not found: {DB_PATH}")

    LEARNING_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        trading_date = _resolve_target_date(con, target_date)
        rows = _load_day_rows(con, trading_date)

    summary = _summarize_rows(rows)
    lessons = _build_actionable_lessons(summary)

    evaluator_result = run_model_evaluator()
    optimizer_result = run_weight_optimizer()
    scale_decision = _build_scale_decision(summary, lessons, evaluator_result, optimizer_result)

    day_json = LEARNING_DIR / f"daily_trade_learning_{trading_date}.json"
    day_md = LEARNING_DIR / f"daily_trade_learning_{trading_date}.md"
    day_csv = LEARNING_DIR / f"daily_trade_learning_trades_{trading_date}.csv"

    payload = {
        "trading_date": trading_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "actionable_lessons": lessons,
        "scale_decision": scale_decision,
        "model_evaluator": evaluator_result,
        "weight_optimizer": optimizer_result,
    }

    day_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown(day_md, trading_date, summary, evaluator_result, optimizer_result, lessons, scale_decision)
    _write_daily_csv(day_csv, rows)

    (LEARNING_DIR / "latest_daily_trade_learning.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    (LEARNING_DIR / "latest_daily_trade_learning.md").write_text(
        day_md.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (LEARNING_DIR / "latest_actionable_lessons.json").write_text(
        json.dumps(
            {
                "trading_date": trading_date,
                "generated_at": payload["generated_at"],
                "actionable_lessons": lessons,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (LEARNING_DIR / "latest_scale_decision.json").write_text(
        json.dumps(
            {
                "trading_date": trading_date,
                "generated_at": payload["generated_at"],
                "scale_decision": scale_decision,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Daily learning date: {trading_date}")
    print(f"Wrote: {day_json}")
    print(f"Wrote: {day_md}")
    print(f"Wrote: {day_csv}")
    print(f"Scale decision: {scale_decision.get('decision')} | +1 allowed={scale_decision.get('increase_allowed')}")

    # model_evaluator currently returns a payload without explicit status;
    # reaching this point without exception means evaluator completed.
    eval_status = str(evaluator_result.get("status", "ok"))
    opt_status = str(optimizer_result.get("status", "unknown"))
    print(f"model_evaluator status: {eval_status}")
    print(f"weight_optimizer status: {opt_status}")

    nonfatal_optimizer = {"ok", "insufficient_history", "insufficient_samples"}
    ok = eval_status == "ok" and opt_status in nonfatal_optimizer
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run daily trade-learning workflow")
    parser.add_argument("--date", help="Trading date YYYY-MM-DD (default: latest available)")
    args = parser.parse_args()

    return run_daily_learning(target_date=args.date)


if __name__ == "__main__":
    raise SystemExit(main())
